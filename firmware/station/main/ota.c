/*
 * ota.c , OTA model delivery, the STATION side that pushes trained models to the collar.
 *
 * Phase 3 of the model pipeline: training/cloud produces .tflite models and bumps an integer
 * version in RTDB; this module notices, downloads the models from Storage, and streams them to the
 * collar over BLE. The wire protocol , opcodes, status codes, the begin header and the three GATT
 * UUIDs , is FINAL in firmware/common/meow_ota.h and shared with the collar; read it for the
 * transfer contract. We are the GATT CLIENT; the collar is the server that stages bytes into flash.
 *
 * THE FLOW, end to end:
 *   1. GATE (ota_push_due): read the model version from RTDB models/<owner>/ver (missing == 0) and
 *      compare it to the per-station last-pushed version in NVS. Newer == a push is due. The cloud
 *      bumping models/<owner>/ver when it deploys a model is OUT OF SCOPE here (see station README).
 *   2. DOWNLOAD (per slot): GET the slot's .tflite from Storage over HTTPS into a heap buffer
 *      (PSRAM-preferred). The models/<owner>/ tree is public-read; a 404 just means that slot has
 *      no model yet , skip it, don't fail the whole push.
 *   3. CRC: CRC-32/IEEE (zlib poly, reflected 0xEDB88320, init/xor 0xFFFFFFFF) over the bytes ,
 *      computed here byte-for-byte the same as the collar's Zephyr crc32_ieee , and announced in BEGIN.
 *   4. PUSH (ota_run_push): discover the OTA service + CONTROL/DATA chars on the connected collar,
 *      subscribe to CONTROL notifications, write BEGIN and wait for READY, stream the model to DATA
 *      in (MTU-3) chunks with write-with-response (the collar's flash-write flow control), write END
 *      and wait for OK. On OK, record the new version in NVS so the gate goes quiet until the next
 *      cloud bump; on any error/abort, leave NVS alone so it retries next cycle.
 *
 * Integration: ota_run_push opens its OWN brief BLE connection (its own GAP callback) to the collar
 * and BLOCKS the calling task on FreeRTOS notifications signalled from that callback. The service
 * loop only calls it when audio capture is idle, so OTA and capture never contend for the radio ,
 * the existing capture/relay behaviour is untouched.
 */
#include "ota.h"
#include "ble.h"
#include "config.h"
#include "cloud.h"
#include "meow_ota.h"        /* FINAL shared wire protocol (firmware/common) */

#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "cJSON.h"
#include "nimble/nimble_port.h"
#include "host/ble_gap.h"
#include "host/ble_gatt.h"
#include "host/ble_hs.h"
#include "os/os_mbuf.h"

static const char *TAG = "meowtion-ota";

/* Storage download. The models/<uid>/ tree is public-read, so we GET the .tflite directly from
 * the Firebase Storage download API (no token). The object name's slashes are %2F-encoded. */
#define STORAGE_HOST "https://firebasestorage.googleapis.com/v0/b/meowtion-app.firebasestorage.app/o"
#define MODEL_MAX_BYTES (192 * 1024)   /* models are <= ~188 KB; cap the download buffer here */

/* The collar's slots map to these object names under models/<uid>/. These MUST match the names the
 * `train` Cloud Function writes (app/firebase/functions/main.py: models/<uid>/<name>_model.tflite). */
static const char *SLOT_FILE[MEOW_OTA_SLOT_COUNT] = {
    [MEOW_OTA_SLOT_IMU]   = "imu_model.tflite",
    [MEOW_OTA_SLOT_AUDIO] = "audio_model.tflite",
};

/* ---- the three OTA GATT UUIDs, built straight from the shared little-endian byte arrays ----
 * NimBLE's ble_uuid128_t stores the 128-bit value little-endian, so MEOW_OTA_*_UUID_BYTES drop in
 * directly as the .value array. (The arrays are already braced { ... }, so we assign them to the
 * struct field rather than passing them through BLE_UUID128_INIT, which would double-brace.) */
static const ble_uuid128_t ota_svc_uuid  = { .u = { .type = BLE_UUID_TYPE_128 }, .value = MEOW_OTA_SVC_UUID_BYTES };
static const ble_uuid128_t ota_ctrl_uuid = { .u = { .type = BLE_UUID_TYPE_128 }, .value = MEOW_OTA_CTRL_UUID_BYTES };
static const ble_uuid128_t ota_data_uuid = { .u = { .type = BLE_UUID_TYPE_128 }, .value = MEOW_OTA_DATA_UUID_BYTES };

/* =============================== CRC-32/IEEE ===============================
 * Reflected zlib polynomial 0xEDB88320, init 0xFFFFFFFF, final XOR 0xFFFFFFFF , identical to the
 * collar's Zephyr crc32_ieee. Implemented by hand (bitwise) rather than trusting an esp_rom variant
 * whose init/xor convention may differ; the CRC must match the collar's re-read byte-for-byte. */
static uint32_t crc32_ieee(const uint8_t *p, size_t n)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++) {
        crc ^= p[i];
        for (int b = 0; b < 8; b++)
            crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1)));
    }
    return crc ^ 0xFFFFFFFFu;
}

/* =============================== version gate ===============================
 * The deployed model version. The cloud `train` function bumps users/<uid>/models/version, but the
 * tokenless station can read ONLY its own /users/<owner>/devices/<token>/ subtree (the DB rules
 * authorise that path by the token in it, not users/<uid>/models above it). So `train` mirrors the
 * version down into this station's own config as `modelVer`, and we read it like any other config
 * value via dev_read(). A missing node parses as 0 (RTDB returns the literal "null"). */
static uint32_t rtdb_model_ver(void)
{
    char resp[64];
    int st = dev_read("/config/modelVer", resp, sizeof resp);
    if (st != 200) { ESP_LOGW(TAG, "modelVer read failed (http %d)", st); return 0; }
    long v = strtol(resp, NULL, 10);   /* bare JSON integer, or "null" when absent */
    return (v > 0) ? (uint32_t)v : 0;
}

bool ota_push_due(void)
{
    if (!g_owner[0]) return false;
    uint32_t cloud = rtdb_model_ver();
    uint32_t local = nvs_get_model_ver();
    if (cloud > local) {
        ESP_LOGI(TAG, "model push due: cloud ver %u > local %u", (unsigned)cloud, (unsigned)local);
        return true;
    }
    return false;
}

/* =============================== Storage download ===============================
 * GET models/<uid>/<file> from Storage into `buf` (cap bytes). Returns the byte length, 0 on a 404
 * (no model for that slot , caller skips it), or -1 on any other error. Streams the body in chunks
 * so we never need a second copy. */
static int download_model(int slot, uint8_t *buf, int cap)
{
    char url[384];
    snprintf(url, sizeof url, "%s/models%%2F%s%%2F%s?alt=media",
             STORAGE_HOST, g_owner, SLOT_FILE[slot]);

    esp_http_client_config_t cfg = {
        .url = url, .method = HTTP_METHOD_GET, .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = 20000,
    };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (!c) return -1;

    int out = -1;
    if (esp_http_client_open(c, 0) != ESP_OK) { esp_http_client_cleanup(c); return -1; }
    esp_http_client_fetch_headers(c);
    int status = esp_http_client_get_status_code(c);
    if (status == 404) {
        out = 0;                                  /* slot has no model yet , not an error */
    } else if (status == 200) {
        int got = 0;
        while (got < cap) {
            int r = esp_http_client_read(c, (char *)buf + got, cap - got);
            if (r < 0) { got = -1; break; }
            if (r == 0) break;                    /* end of body */
            got += r;
        }
        if (got >= 0 && !esp_http_client_is_complete_data_received(c)) {
            ESP_LOGW(TAG, "slot %d model exceeds %d B buffer", slot, cap);
            got = -1;                             /* truncated , refuse to push a partial model */
        }
        out = got;
    } else {
        ESP_LOGW(TAG, "slot %d download http %d", slot, status);
    }
    esp_http_client_close(c);
    esp_http_client_cleanup(c);
    return out;
}

/* =============================== BLE OTA push ===============================
 * A small blocking state machine. ota_run_push() (called from the service-loop task) connects, then
 * blocks on a task notification that the GAP callback (NimBLE host task) raises for each milestone:
 * discovery results, the CONTROL status notify, and each DATA write completion. Mirrors the way
 * ble.c structures its capture discovery/subscribe, but stays in this module's own connection. */

#define OTA_EVT_TIMEOUT_MS 8000          /* per-step wait (discovery, READY, each write, END->OK) */
#define OTA_CONN_TIMEOUT_MS 8000         /* connect establish */

/* Events posted from the GAP callback to the waiting push task (task-notification bits). */
#define EV_CONNECTED   (1 << 0)
#define EV_CONN_FAIL   (1 << 1)
#define EV_DISCONN     (1 << 2)
#define EV_SVC_DONE    (1 << 3)          /* service discovery finished (found_* tells us what) */
#define EV_CHR_DONE    (1 << 4)          /* characteristic discovery finished */
#define EV_STATUS      (1 << 5)          /* a CONTROL status notification arrived (g_status) */
#define EV_WRITE_DONE  (1 << 6)          /* a GATT write completed (g_write_rc has the status) */

static TaskHandle_t      g_push_task = NULL;   /* task to notify (the caller of ota_run_push) */
static volatile uint16_t g_conn = BLE_HS_CONN_HANDLE_NONE;
static volatile uint16_t g_ctrl_handle = 0;    /* CONTROL value handle */
static volatile uint16_t g_ctrl_cccd = 0;      /* CONTROL CCCD handle (val_handle + 1) */
static volatile uint16_t g_data_handle = 0;    /* DATA value handle */
static volatile uint16_t g_svc_start = 0, g_svc_end = 0;
static volatile uint8_t  g_status = 0xff;      /* last CONTROL status byte */
static volatile int      g_write_rc = -1;      /* last write's GATT status */
static volatile uint16_t g_mtu = 23;           /* negotiated ATT MTU (chunk = mtu-3) */

/* Block until any of `bits` is signalled, or timeout. Returns the bits seen (0 on timeout). */
static uint32_t wait_evt(uint32_t bits, int timeout_ms)
{
    uint32_t got = 0;
    TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
    for (;;) {
        uint32_t n = 0;
        TickType_t now = xTaskGetTickCount();
        TickType_t wait = (now < deadline) ? (deadline - now) : 0;
        if (xTaskNotifyWait(0, 0xffffffff, &n, wait) == pdTRUE) {
            got |= n;
            if (got & bits) return got & bits;
            if (got & (EV_CONN_FAIL | EV_DISCONN)) return got & (EV_CONN_FAIL | EV_DISCONN);
        }
        if (xTaskGetTickCount() >= deadline) return 0;
    }
}

/* Block until ALL of `need` have been signalled (events can arrive in any order across separate
 * notifications, so we accumulate), or a link-loss event, or timeout. Returns the accumulated bits;
 * the caller checks (got & need) == need. This avoids the lost-bit race of two sequential wait_evt()
 * calls when, e.g., a write-response and a status notify land before this task is scheduled. */
static uint32_t wait_evt_all(uint32_t need, int timeout_ms)
{
    uint32_t got = 0;
    TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
    for (;;) {
        uint32_t n = 0;
        TickType_t now = xTaskGetTickCount();
        TickType_t wait = (now < deadline) ? (deadline - now) : 0;
        if (xTaskNotifyWait(0, 0xffffffff, &n, wait) == pdTRUE) {
            got |= n;
            if ((got & need) == need) return got;
            if (got & (EV_CONN_FAIL | EV_DISCONN)) return got;
        }
        if (xTaskGetTickCount() >= deadline) return 0;
    }
}

static void notify_push(uint32_t bit)
{
    if (g_push_task) xTaskNotify(g_push_task, bit, eSetBits);
}

/* ---- GATT discovery callbacks (NimBLE host task) ---- */
static int on_data_chr(uint16_t ch, const struct ble_gatt_error *err,
                       const struct ble_gatt_chr *chr, void *arg)
{
    if (err->status == 0 && chr) g_data_handle = chr->val_handle;
    else if (err->status == BLE_HS_EDONE) notify_push(EV_CHR_DONE);
    return 0;
}
static int on_ctrl_chr(uint16_t ch, const struct ble_gatt_error *err,
                       const struct ble_gatt_chr *chr, void *arg)
{
    if (err->status == 0 && chr) {
        g_ctrl_handle = chr->val_handle;
        g_ctrl_cccd   = chr->val_handle + 1;   /* CCC descriptor sits right after the value */
    } else if (err->status == BLE_HS_EDONE) {
        /* CONTROL found (or not); now discover DATA in the same service range. */
        ble_gattc_disc_chrs_by_uuid(ch, g_svc_start, g_svc_end, &ota_data_uuid.u, on_data_chr, NULL);
    }
    return 0;
}
static int on_ota_svc(uint16_t ch, const struct ble_gatt_error *err,
                      const struct ble_gatt_svc *svc, void *arg)
{
    if (err->status == 0 && svc) {
        g_svc_start = svc->start_handle;
        g_svc_end   = svc->end_handle;
    } else if (err->status == BLE_HS_EDONE) {
        notify_push(EV_SVC_DONE);
    }
    return 0;
}

/* Each CONTROL/DATA write completion lands here (write-with-response). */
static int on_write(uint16_t ch, const struct ble_gatt_error *err,
                    struct ble_gatt_attr *attr, void *arg)
{
    g_write_rc = err ? err->status : 0;
    notify_push(EV_WRITE_DONE);
    return 0;
}

static int on_mtu_cb(uint16_t ch, const struct ble_gatt_error *err, uint16_t mtu, void *arg)
{
    if (!(err && err->status) && mtu >= 23) g_mtu = mtu;
    return 0;
}

/* The OTA connection's GAP callback , a sibling of ble.c's central_gap_cb but for this module's
 * own short-lived connection. It only translates link events into push-task notifications. */
static int ota_gap_cb(struct ble_gap_event *event, void *arg)
{
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            g_conn = event->connect.conn_handle;
            notify_push(EV_CONNECTED);
        } else {
            notify_push(EV_CONN_FAIL);
        }
        return 0;
    case BLE_GAP_EVENT_DISCONNECT:
        g_conn = BLE_HS_CONN_HANDLE_NONE;
        notify_push(EV_DISCONN);
        return 0;
    case BLE_GAP_EVENT_NOTIFY_RX:
        if (event->notify_rx.attr_handle == g_ctrl_handle && event->notify_rx.om) {
            uint8_t b;
            if (os_mbuf_copydata(event->notify_rx.om, 0, 1, &b) == 0) {
                g_status = b;
                notify_push(EV_STATUS);
            }
        }
        return 0;
    case BLE_GAP_EVENT_MTU:
        if (event->mtu.value >= 23) g_mtu = event->mtu.value;
        return 0;
    default:
        return 0;
    }
}

/* Write CONTROL and wait for a specific status notify (bail on any ERR_* / timeout).
 * The collar acks the write (EV_WRITE_DONE) AND notifies a status byte (EV_STATUS); these can arrive
 * in either order, so we accumulate until BOTH are seen rather than waiting for them sequentially
 * (which could lose the status bit if both land before this task runs). Stale notification bits from
 * the previous step are cleared first so they can't satisfy this wait early. */
static bool ctrl_write_wait(const uint8_t *buf, int len, uint8_t want)
{
    xTaskNotifyStateClear(NULL);
    g_status = 0xff;
    g_write_rc = -1;
    if (ble_gattc_write_flat(g_conn, g_ctrl_handle, buf, len, on_write, NULL) != 0) return false;
    uint32_t got = wait_evt_all(EV_WRITE_DONE | EV_STATUS, OTA_EVT_TIMEOUT_MS);
    if ((got & (EV_WRITE_DONE | EV_STATUS)) != (EV_WRITE_DONE | EV_STATUS) || g_write_rc != 0) {
        return false;
    }
    if (g_status != want) {
        ESP_LOGW(TAG, "control: got status %u, wanted %u", g_status, want);
        return false;
    }
    return true;
}

/* Push one downloaded model (len bytes, already CRC'd) to the connected collar. */
static bool push_slot(int slot, const uint8_t *model, uint32_t len, uint32_t crc)
{
    /* BEGIN: [op][meow_ota_begin] , erase + arm the slot, wait for READY. */
    uint8_t begin[1 + sizeof(struct meow_ota_begin)];
    begin[0] = MEOW_OTA_OP_BEGIN;
    struct meow_ota_begin hb = { .slot = (uint8_t)slot, ._rsvd = 0, .total_len = len, .crc32 = crc };
    memcpy(begin + 1, &hb, sizeof hb);
    if (!ctrl_write_wait(begin, sizeof begin, MEOW_OTA_ST_READY)) {
        ESP_LOGE(TAG, "slot %d BEGIN not READY (status %u)", slot, g_status);
        return false;
    }

    /* DATA: stream (MTU-3) chunks, write-with-response. Each write-response is the collar's flash-write
     * flow control (it returns only once that chunk is programmed); the collar stays silent on the
     * status channel during streaming, so the only event per chunk is EV_WRITE_DONE. */
    xTaskNotifyStateClear(NULL);
    uint16_t chunk = (g_mtu > 23) ? (g_mtu - 3) : 20;
    for (uint32_t off = 0; off < len; off += chunk) {
        uint16_t n = (len - off < chunk) ? (uint16_t)(len - off) : chunk;
        g_write_rc = -1;
        if (ble_gattc_write_flat(g_conn, g_data_handle, model + off, n, on_write, NULL) != 0) {
            ESP_LOGE(TAG, "slot %d DATA write submit failed at %u", slot, (unsigned)off);
            return false;
        }
        if (!(wait_evt(EV_WRITE_DONE, OTA_EVT_TIMEOUT_MS) & EV_WRITE_DONE) || g_write_rc != 0) {
            ESP_LOGE(TAG, "slot %d DATA write stalled at %u (rc %d)", slot, (unsigned)off, g_write_rc);
            return false;
        }
    }

    /* END: collar re-reads flash, verifies CRC, commits the slot header, loads the model. */
    uint8_t end = MEOW_OTA_OP_END;
    if (!ctrl_write_wait(&end, 1, MEOW_OTA_ST_OK)) {
        ESP_LOGE(TAG, "slot %d END not OK (status %u)", slot, g_status);
        return false;
    }
    ESP_LOGI(TAG, "slot %d pushed OK (%u B)", slot, (unsigned)len);
    return true;
}

/* Best-effort ABORT so a failed slot leaves the collar idle (it also discards on disconnect). */
static void push_abort(void)
{
    if (g_conn == BLE_HS_CONN_HANDLE_NONE || g_ctrl_handle == 0) return;
    uint8_t op = MEOW_OTA_OP_ABORT;
    g_write_rc = -1;
    if (ble_gattc_write_flat(g_conn, g_ctrl_handle, &op, 1, on_write, NULL) == 0)
        wait_evt(EV_WRITE_DONE, OTA_EVT_TIMEOUT_MS);
}

bool ota_run_push(uint16_t conn_handle)
{
    /* conn_handle is unused: ota_run_push owns its own connection to keep the radio uncontended
     * with capture (the service loop guarantees capture is idle before calling us). */
    (void)conn_handle;

    ble_addr_t addr;
    if (!ble_near_collar_addr(&addr)) {
        ble_resume_scan();   /* revive the scanner if a prior push left it off, so relay + the next push recover */
        ESP_LOGW(TAG, "push: no collar in range");
        return false;
    }

    uint32_t cloud_ver = rtdb_model_ver();
    if (cloud_ver == 0) return false;

    /* One heap buffer reused for both slots (PSRAM-preferred, internal RAM fallback). */
    uint8_t *model = heap_caps_malloc(MODEL_MAX_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!model) model = heap_caps_malloc(MODEL_MAX_BYTES, MALLOC_CAP_8BIT);
    if (!model) { ESP_LOGE(TAG, "push: model buffer alloc failed"); return false; }

    /* Reset push state and connect (our own GAP callback). */
    g_push_task = xTaskGetCurrentTaskHandle();
    xTaskNotifyStateClear(g_push_task);
    g_conn = BLE_HS_CONN_HANDLE_NONE;
    g_ctrl_handle = g_data_handle = g_ctrl_cccd = 0;
    g_svc_start = g_svc_end = 0;
    g_mtu = 23;

    ble_gap_disc_cancel();   /* stop scanning so the connect can proceed */
    struct ble_gap_conn_params cp = {
        .scan_itvl = 0x0010, .scan_window = 0x0010,
        .itvl_min = 24, .itvl_max = 40,            /* 30-50 ms , relaxed; throughput isn't critical */
        .latency = 0, .supervision_timeout = 400,
        .min_ce_len = 0, .max_ce_len = 0x0100,
    };
    bool any_ok = false, all_present_ok = true, pushed_any_slot = false;
    int rc = ble_gap_connect(ble_own_addr_type(), &addr, OTA_CONN_TIMEOUT_MS, &cp, ota_gap_cb, NULL);
    if (rc) { ESP_LOGE(TAG, "ota connect rc=%d", rc); goto done; }
    if (!(wait_evt(EV_CONNECTED, OTA_CONN_TIMEOUT_MS + 1000) & EV_CONNECTED)) {
        ESP_LOGW(TAG, "ota connect timeout");
        goto done;
    }

    /* Larger MTU (more bytes per DATA chunk) + discover the OTA service. */
    ble_gattc_exchange_mtu(g_conn, on_mtu_cb, NULL);
    if (ble_gattc_disc_svc_by_uuid(g_conn, &ota_svc_uuid.u, on_ota_svc, NULL) != 0) goto disconnect;
    if (!(wait_evt(EV_SVC_DONE, OTA_EVT_TIMEOUT_MS) & EV_SVC_DONE) || g_svc_start == 0) {
        ESP_LOGE(TAG, "OTA service not found on collar");
        goto disconnect;
    }
    if (ble_gattc_disc_chrs_by_uuid(g_conn, g_svc_start, g_svc_end, &ota_ctrl_uuid.u,
                                    on_ctrl_chr, NULL) != 0) goto disconnect;
    if (!(wait_evt(EV_CHR_DONE, OTA_EVT_TIMEOUT_MS) & EV_CHR_DONE) ||
        g_ctrl_handle == 0 || g_data_handle == 0) {
        ESP_LOGE(TAG, "OTA chars missing (ctrl=%u data=%u)", g_ctrl_handle, g_data_handle);
        goto disconnect;
    }

    /* Subscribe to CONTROL notifications (write its CCC = 0x0001) so we get the status bytes. */
    uint8_t en[2] = { 0x01, 0x00 };
    g_write_rc = -1;
    if (ble_gattc_write_flat(g_conn, g_ctrl_cccd, en, sizeof en, on_write, NULL) != 0 ||
        !(wait_evt(EV_WRITE_DONE, OTA_EVT_TIMEOUT_MS) & EV_WRITE_DONE) || g_write_rc != 0) {
        ESP_LOGE(TAG, "CONTROL subscribe failed (rc %d)", g_write_rc);
        goto disconnect;
    }

    /* For each slot present in Storage, download -> CRC -> push. A 404 (len 0) skips the slot; a
     * download error fails just that slot, not the whole push. */
    for (int slot = 0; slot < MEOW_OTA_SLOT_COUNT; slot++) {
        int len = download_model(slot, model, MODEL_MAX_BYTES);
        if (len == 0) { ESP_LOGI(TAG, "slot %d: no model in Storage, skip", slot); continue; }
        if (len < 0)  { ESP_LOGW(TAG, "slot %d: download failed", slot); all_present_ok = false; continue; }
        uint32_t crc = crc32_ieee(model, len);
        ESP_LOGI(TAG, "slot %d: %d B crc=0x%08x , pushing", slot, len, (unsigned)crc);
        pushed_any_slot = true;
        if (push_slot(slot, model, (uint32_t)len, crc)) {
            any_ok = true;
        } else {
            all_present_ok = false;
            push_abort();      /* discard the partial; collar keeps its previous model */
        }
    }

disconnect:
    if (g_conn != BLE_HS_CONN_HANDLE_NONE) {
        ble_gap_terminate(g_conn, BLE_ERR_REM_USER_CONN_TERM);
        wait_evt(EV_DISCONN, 2000);
    }
done:
    g_push_task = NULL;
    free(model);
    ble_resume_scan();   /* we cancelled scanning to connect; resume the observer so telemetry relay continues */

    /* Only advance the NVS version when every model that EXISTS in Storage was delivered OK , so a
     * partial failure retries next cycle. (If no slot had a model at all, there's nothing to push;
     * don't bump, in case Storage just hasn't been populated yet.) */
    if (pushed_any_slot && all_present_ok && any_ok) {
        nvs_set_model_ver(cloud_ver);
        ESP_LOGI(TAG, "push complete, recorded model ver %u", (unsigned)cloud_ver);
    } else {
        ESP_LOGW(TAG, "push incomplete (any_ok=%d all_present_ok=%d) , will retry", any_ok, all_present_ok);
    }
    return any_ok;
}
