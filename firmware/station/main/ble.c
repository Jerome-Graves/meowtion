/*
 * ble.c , the NimBLE collar subsystem (scan/relay + audio capture).
 *
 * This is the whole BLE side of the station, kept behind the small interface in ble.h so main.c
 * never reaches into its internals:
 *   - Observer: passively scan for the collar's manufacturer advert, keep a small table keyed by
 *     BLE address, and relay each registered collar's telemetry to /cats/{id}.
 *   - Central: when a registered collar is in range, connect, subscribe to its audio
 *     characteristic, reassemble the continuous 100 ms frame stream into fixed-length WAV clips
 *     (+ paired IMU sidecar), and upload them via the upload_clip Cloud Function.
 * The capture state machine is serviced once per ~1 s tick by ble_service(); the scan callback and
 * frame parser run in the NimBLE host task, so the clip buffers ping-pong between the two tasks.
 */
#include "ble.h"
#include "config.h"
#include "cloud.h"
#include "board.h"
#include "meow_protocol.h"   /* shared collar<->station wire format + µ-law (firmware/common) */

#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "cJSON.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_hs_adv.h"
#include "host/ble_gap.h"
#include "host/ble_gatt.h"
#include "host/util/util.h"
#include "os/os_mbuf.h"

static const char *TAG = "meowtion-ble";

/* collar behaviour states, indexed by the collar packet's state byte (0..5) */
static const char *STATES[] = { "sleep", "rest", "active", "walk", "play", "groom" };

/* The collar sets this state/class byte while in low-power rest (cascade tier 0). It is distinct
 * from a model class index (0..N-1) and from 0xFF=UNKNOWN, so a rest span becomes its own episode. */
#define COLLAR_STATE_REST 0xFE

/* Human label for a state/class byte: low-power rest, unknown, else the behaviour name. */
static const char *state_name(uint8_t s)
{
    if (s == COLLAR_STATE_REST) return "rest";
    if (s == 0xFF)              return "unknown";
    return STATES[s % 6];
}

/* registered-collar allow-list (the "2 devices" gate); populated by ble_fetch_allow() below */
#define MAX_ALLOW 8
static char g_allow[MAX_ALLOW][16];
static int  g_allow_n = 0;

/* ---------------- BLE scanner: relay real collars ----------------
 * The collar BROADCASTS an 8-byte manufacturer packet (company 0xFFFF):
 *   [0..1] company id LE  [2] version  [3] state(0..5)  [4] activity  [5..6] steps LE  [7] battery
 * We passively scan, parse it in the NimBLE host callback into a small table (keyed by the
 * collar's BLE address), and the main loop relays the freshest snapshot to Firebase. The table
 * only ever holds registered collars; unregistered ones go to /seen so the dashboard can adopt them. */
#define COLLAR_COMPANY_ID 0xFFFF
#define MAX_COLLARS       4
#define COLLAR_STALE_MS   30000      /* a collar unseen this long is dropped */

typedef struct {
    bool     used;
    uint8_t  addr[6];
    char     id[16];                 /* "cat_aabbcc" from the BLE address */
    /* latest from the advertisement (written by the scan callback) */
    uint8_t  ver;                    /* packet version: 1 = simulated, 2 = real on-device classification */
    uint8_t  state, activity, battery;
    uint16_t steps;
    int64_t  last_ms;
    /* episode tracking (owned by the relay in the main loop) */
    bool     reported;
    uint8_t  cur_state;
    int64_t  state_start;
} collar_t;

static collar_t          g_collars[MAX_COLLARS];
static SemaphoreHandle_t  g_collar_mtx;

/* Proximity (signal strength) of the collar we currently hear, for the dev view + capture gate.
 * Updated in collar_ingest under g_collar_mtx; read by ble_publish_dev() in the main loop. */
static int       g_near_rssi = -128;    /* smoothed RSSI of the most recent collar packet */
static char      g_near_id[16] = "";
static int64_t   g_near_ms = 0;
static ble_addr_t g_near_addr;          /* full BLE address of the collar we hear (to connect to) */
static int       g_rssi_threshold = -60;/* in-range cutoff (the dev view writes this to config) */
static int       g_dwell_ms = 2000;     /* must stay in range this long before "inRange" */
static bool      g_capture_on = false;  /* dev-view toggle: record audio clips for training? */
static bool      g_force_capture = false;/* dev-view override: capture whenever a collar is heard, ignore range (for purr) */
static bool      g_production = false;   /* config "mode": production = never capture/stream/upload, just relay the collar's on-device classification */
static uint8_t   g_own_addr_type = 0;   /* our BLE address type, for scan + connect */
static volatile bool g_inrange = false; /* set by ble_publish_dev: collar dwell-confirmed in range */
static volatile bool g_heard = false;   /* set by ble_publish_dev: a collar heard in the last 5 s (any distance) */

/* audio-capture state machine (the capture functions are defined further down) */
typedef enum { CAP_IDLE, CAP_CONNECTING, CAP_RECEIVING } cap_state_t;
static volatile cap_state_t g_cap = CAP_IDLE;

/* unregistered collars we currently hear , published to devices/{token}/seen so the dashboard
 * can offer to register them (collar USB serial is unreliable, so we discover over BLE instead) */
#define MAX_SEEN       4
#define SEEN_STALE_MS  60000
typedef struct { bool used; char id[16]; int64_t last_ms; } seen_t;
static seen_t g_seen[MAX_SEEN];

static void start_scan(void);
static void start_capture(void);

/* The dashboard registers a collar by writing devices/{token}/allowedCollars/{id}=true. The
 * station reads that list (over HTTPS, authorised by its own token) and relays ONLY collars on
 * it. With no collar registered the list is empty and nothing is relayed, so cat data flows
 * only once BOTH a station and a collar are registered to the account.
 * caller must hold g_collar_mtx */
static bool is_allowed(const char *id)
{
    for (int i = 0; i < g_allow_n; i++) if (strcmp(g_allow[i], id) == 0) return true;
    return false;
}

int ble_allowed_count(void) { return g_allow_n; }

/* ---- OTA support: expose just enough for ota.c to connect to the in-range collar ----
 * ota.c runs an entirely separate, brief BLE connection (its own GAP callback) to push a model;
 * the service loop only lets it run when capture is idle, so the two never share the radio. */
bool ble_capture_active(void)
{
    return g_cap != CAP_IDLE;
}

uint8_t ble_own_addr_type(void) { return g_own_addr_type; }

/* Copy the address of the collar we currently hear (the same one start_capture connects to) into
 * `out` (a ble_addr_t*). Returns false if no collar has been heard recently. */
bool ble_near_collar_addr(void *out)
{
    bool ok = false;
    xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
    if ((now_ms() - g_near_ms) < 5000 && g_near_rssi > -128) {
        memcpy(out, &g_near_addr, sizeof(ble_addr_t));
        ok = true;
    }
    xSemaphoreGive(g_collar_mtx);
    return ok;
}

void ble_fetch_allow(void)
{
    static char resp[1024];
    if (dev_read("/allowedCollars", resp, sizeof resp) != 200) return;   /* keep last list on error */
    cJSON *j = cJSON_Parse(resp);
    xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
    g_allow_n = 0;
    if (cJSON_IsObject(j))
        for (cJSON *it = j->child; it && g_allow_n < MAX_ALLOW; it = it->next)
            if (it->string) snprintf(g_allow[g_allow_n++], 16, "%s", it->string);
    int n = g_allow_n;
    xSemaphoreGive(g_collar_mtx);
    cJSON_Delete(j);
    ESP_LOGI(TAG, "registered collars: %d", n);
}

/* read the dev view's capture-range settings (devices/{token}/config) */
void ble_fetch_config(void)
{
    static char resp[256];
    if (dev_read("/config", resp, sizeof resp) != 200) return;   /* keep defaults on error */
    cJSON *j = cJSON_Parse(resp);
    if (cJSON_IsObject(j)) {
        cJSON *t = cJSON_GetObjectItem(j, "rssiThreshold");
        cJSON *d = cJSON_GetObjectItem(j, "dwellMs");
        cJSON *cap = cJSON_GetObjectItem(j, "capture");
        cJSON *force = cJSON_GetObjectItem(j, "captureForce");
        cJSON *mode = cJSON_GetObjectItem(j, "mode");
        if (cJSON_IsNumber(t)) g_rssi_threshold = t->valueint;
        if (cJSON_IsNumber(d)) g_dwell_ms = d->valueint;
        g_capture_on = cJSON_IsTrue(cap);
        g_force_capture = cJSON_IsTrue(force);
        g_production = cJSON_IsString(mode) && strcmp(mode->valuestring, "production") == 0;
        ESP_LOGI(TAG, "config: threshold=%d dwell=%d capture=%d force=%d mode=%s",
                 g_rssi_threshold, g_dwell_ms, g_capture_on, g_force_capture,
                 g_production ? "production" : "training");
    }
    cJSON_Delete(j);
}

/* ---------------- station presence heartbeat (always, independent of the cat source) ---------------- */
void ble_heartbeat(void)
{
    read_power();
    int64_t now = now_ms();
    char hb[128];
    if (g_batt_pct >= 0)
        snprintf(hb, sizeof hb, "{\"lastSeen\":%lld,\"power\":\"battery\",\"battery\":%d,\"collars\":%d}",
                 (long long)now, g_batt_pct, g_allow_n);
    else
        snprintf(hb, sizeof hb, "{\"lastSeen\":%lld,\"power\":\"usb\",\"collars\":%d}", (long long)now, g_allow_n);
    dev_write(HTTP_METHOD_PATCH, "", hb);   /* station presence + power + registered-collar count */
}

/* publish live proximity status to devices/{token}/dev for the dev view: the collar's signal,
 * which collar it is, and whether it's idle / approaching / in-range (dwell-confirmed). */
void ble_publish_dev(void)
{
    static int64_t inrange_since = 0;
    int64_t now = now_ms();

    xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
    int rssi = g_near_rssi; int64_t nm = g_near_ms;
    char id[16]; snprintf(id, sizeof id, "%s", g_near_id);
    xSemaphoreGive(g_collar_mtx);

    bool heard = (now - nm) < 5000 && rssi > -128;     /* collar heard in the last 5 s */
    const char *state = "idle";
    if (heard && rssi >= g_rssi_threshold) {           /* stronger (less negative) = closer */
        if (inrange_since == 0) inrange_since = now;
        state = ((now - inrange_since) >= g_dwell_ms) ? "inRange" : "approaching";
    } else {
        inrange_since = 0;
    }
    g_inrange = (state[0] == 'i' && state[1] == 'n');  /* "inRange" , the capture trigger */
    g_heard = heard;                                   /* force-capture trigger (ignores range) */
    if (g_cap == CAP_CONNECTING || g_cap == CAP_RECEIVING) state = "recording";   /* dev view badge */

    char body[160];
    if (heard)
        snprintf(body, sizeof body, "{\"rssi\":%d,\"nearCollar\":\"%s\",\"state\":\"%s\",\"updatedAt\":%lld}",
                 rssi, id, state, (long long)now);
    else
        snprintf(body, sizeof body, "{\"rssi\":null,\"nearCollar\":null,\"state\":\"idle\",\"updatedAt\":%lld}",
                 (long long)now);
    dev_write(HTTP_METHOD_PUT, "/dev", body);
}

/* Runs in the NimBLE host task for every matching advertisement. Keep it short: just update
 * the table; all HTTPS happens later in the main loop. p = the 6 bytes after the company id. */
static void collar_ingest(const ble_addr_t *ba, const uint8_t *p, int8_t rssi)
{
    const uint8_t *addr = ba->val;
    char id[16];
    snprintf(id, sizeof id, "cat_%02x%02x%02x", addr[2], addr[1], addr[0]);
    int64_t now = now_ms();
    xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
    /* proximity: smooth the signal of whatever collar we hear (any one, so it works even before
     * registration), for the dev view + the in-range gate */
    g_near_rssi = (g_near_rssi <= -128) ? rssi : (g_near_rssi * 3 + rssi) / 4;
    snprintf(g_near_id, sizeof g_near_id, "%s", id);
    g_near_addr = *ba;
    g_near_ms = now;
    if (!is_allowed(id)) {
        /* heard but not registered: remember it so the dashboard can offer to register it */
        seen_t *s = NULL;
        for (int i = 0; i < MAX_SEEN; i++)
            if (g_seen[i].used && strcmp(g_seen[i].id, id) == 0) { s = &g_seen[i]; break; }
        if (!s)
            for (int i = 0; i < MAX_SEEN; i++)
                if (!g_seen[i].used) { s = &g_seen[i]; s->used = true; snprintf(s->id, sizeof s->id, "%s", id); break; }
        if (s) s->last_ms = now;
        xSemaphoreGive(g_collar_mtx);
        return;
    }
    collar_t *c = NULL;
    for (int i = 0; i < MAX_COLLARS; i++)
        if (g_collars[i].used && memcmp(g_collars[i].addr, addr, 6) == 0) { c = &g_collars[i]; break; }
    if (!c)
        for (int i = 0; i < MAX_COLLARS; i++)
            if (!g_collars[i].used) {
                c = &g_collars[i];
                memset(c, 0, sizeof *c);
                memcpy(c->addr, addr, 6);
                snprintf(c->id, sizeof c->id, "%s", id);
                c->used = true;
                break;
            }
    if (c) {
        /* p points at mfg_data[2]: p[0]=version, p[1]=state/class, p[2]=activity/conf,
         * p[3..4]=steps LE, p[5]=battery. In v2 (real classification) p[1] is the class INDEX
         * (0xFF=UNKNOWN) and p[2] is confidence 0..100; in v1 (simulated) they're state/activity. */
        c->ver      = p[0];
        c->state    = p[1];
        c->activity = p[2];
        c->steps    = p[3] | (p[4] << 8);
        c->battery  = p[5];
        c->last_ms  = now;
    }
    xSemaphoreGive(g_collar_mtx);
}

static int gap_event_cb(struct ble_gap_event *event, void *arg)
{
    if (event->type != BLE_GAP_EVENT_DISC) return 0;
    struct ble_hs_adv_fields f;
    if (ble_hs_adv_parse_fields(&f, event->disc.data, event->disc.length_data) != 0) return 0;
    if (!f.mfg_data || f.mfg_data_len < 2) return 0;
    uint16_t cid = f.mfg_data[0] | (f.mfg_data[1] << 8);
    if (cid != COLLAR_COMPANY_ID || f.mfg_data_len != 8) return 0;
    collar_ingest(&event->disc.addr, &f.mfg_data[2], event->disc.rssi);   /* full addr + rssi */
    return 0;
}

static void start_scan(void)
{
    struct ble_gap_disc_params dp = { 0 };
    dp.passive = 1;                  /* listen only, never request a scan response */
    dp.filter_duplicates = 0;        /* we want repeated telemetry, not just first-seen */
    int rc = ble_gap_disc(g_own_addr_type, BLE_HS_FOREVER, &dp, gap_event_cb, NULL);
    if (rc) ESP_LOGE(TAG, "ble_gap_disc rc=%d", rc);
}

/* Resume the observer scan if it isn't already running. The capture path restarts scanning itself
 * after each connection; the OTA push (ota.c) cancels scanning to connect but uses its own GAP
 * callback, so it calls this when done. Without it the station stays deaf after a push - no telemetry
 * relay and "no collar in range" on every later push. Idempotent: only starts if not discovering. */
void ble_resume_scan(void)
{
    if (!ble_gap_disc_active()) start_scan();
}

static void ble_on_sync(void)
{
    if (ble_hs_id_infer_auto(0, &g_own_addr_type) != 0) { ESP_LOGE(TAG, "no BLE addr"); return; }
    start_scan();
    ESP_LOGI(TAG, "BLE scanning for collars (company 0x%04X)", COLLAR_COMPANY_ID);
}

static void ble_host_task(void *arg)
{
    nimble_port_run();               /* returns only on nimble_port_stop() */
    nimble_port_freertos_deinit();
}

/* Relay every fresh, registered collar to /cats/{id}: a live `current` plus episode events on
 * state change. The table only ever holds registered collars (collar_ingest drops the rest),
 * so this inherently sends nothing until a collar is registered. */
void ble_relay(void)
{
    int64_t now = now_ms();
    for (int i = 0; i < MAX_COLLARS; i++) {
        collar_t snap;
        xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
        snap = g_collars[i];
        xSemaphoreGive(g_collar_mtx);
        if (!snap.used) continue;
        if (now - snap.last_ms > COLLAR_STALE_MS) {       /* collar left / powered off */
            xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
            g_collars[i].used = false;
            xSemaphoreGive(g_collar_mtx);
            ESP_LOGW(TAG, "collar %s stale, dropped", snap.id);
            continue;
        }
        char base[24], body[224], suffix[40];
        snprintf(base, sizeof base, "/cats/%s", snap.id);

        /* Forward the production contract so the dashboard can tell real (ver=2) from simulated
         * (ver=1) and read the model's class index + confidence. `cls` is the raw class byte
         * (0..N-1, or 255 = UNKNOWN/low-confidence) and `conf` the 0..100 confidence; both are only
         * meaningful when ver=2. `state` (the human-readable label) is kept for the v1 dashboard. */
        snprintf(body, sizeof body,
                 "{\"ts\":%lld,\"state\":\"%s\",\"steps\":%u,\"battery\":%d,\"ver\":%u,\"cls\":%u,\"conf\":%u}",
                 (long long)now, state_name(snap.state), (unsigned)snap.steps, snap.battery,
                 (unsigned)snap.ver, (unsigned)snap.state, (unsigned)snap.activity);
        snprintf(suffix, sizeof suffix, "%s/current", base);
        dev_write(HTTP_METHOD_PUT, suffix, body);

        if (!snap.reported) {                             /* first sighting: name it, start episode */
            snprintf(body, sizeof body, "{\"name\":\"%s\"}", snap.id);
            dev_write(HTTP_METHOD_PATCH, base, body);
            xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
            g_collars[i].reported = true;
            g_collars[i].cur_state = snap.state;
            g_collars[i].state_start = now;
            xSemaphoreGive(g_collar_mtx);
        } else if (snap.state != snap.cur_state) {        /* state changed: close the episode */
            int dur = (int)((now - snap.state_start) / 1000);
            /* Carry ver+cls so the dashboard can label a production episode with the model's class
             * name (via cls) instead of the simulated state name; `type` is kept for the v1 path. */
            snprintf(body, sizeof body,
                     "{\"type\":\"%s\",\"start\":%lld,\"durationSec\":%d,\"ver\":%u,\"cls\":%u}",
                     state_name(snap.cur_state), (long long)snap.state_start, dur,
                     (unsigned)snap.ver, (unsigned)snap.cur_state);
            snprintf(suffix, sizeof suffix, "%s/events", base);
            dev_write(HTTP_METHOD_POST, suffix, body);
            xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
            g_collars[i].cur_state = snap.state;
            g_collars[i].state_start = now;
            xSemaphoreGive(g_collar_mtx);
        }
        ESP_LOGI(TAG, "relay %s %s steps=%u batt=%d", snap.id, state_name(snap.state), (unsigned)snap.steps, snap.battery);
    }
}

/* Publish the set of unregistered collars we currently hear to devices/{token}/seen, so the
 * dashboard can list them with a "Register" button. Writes only when the set changes, and
 * clears (null) once they're all registered or gone. */
void ble_publish_seen(void)
{
    static char last[256] = "\x01";   /* sentinel so the first call always writes */
    int64_t now = now_ms();
    char body[256];
    int len = snprintf(body, sizeof body, "{");
    bool any = false;
    xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
    for (int i = 0; i < MAX_SEEN; i++) {
        if (!g_seen[i].used) continue;
        if (now - g_seen[i].last_ms > SEEN_STALE_MS) { g_seen[i].used = false; continue; }
        len += snprintf(body + len, sizeof body - len, "%s\"%s\":true", any ? "," : "", g_seen[i].id);
        any = true;
    }
    xSemaphoreGive(g_collar_mtx);
    snprintf(body + len, sizeof body - len, "}");
    const char *out = any ? body : "null";
    if (strcmp(out, last) != 0) {
        dev_write(HTTP_METHOD_PUT, "/seen", out);
        snprintf(last, sizeof last, "%s", out);
    }
}

/* ================= audio capture: connect to an in-range collar, pull a clip, upload =========
 * When a registered collar is dwell-confirmed in range, the station (BLE central) connects, finds
 * the collar's audio service, subscribes, fills a WAV buffer with CLIP_SECONDS of PCM, disconnects,
 * uploads via the upload_clip Cloud Function and indexes the clip under devices/{token}/clips. The
 * UUIDs MUST match the collar's (little-endian byte order of 4d656f77-0a0X-4175-6469-6f00...). */
static const ble_uuid128_t meow_svc_uuid = BLE_UUID128_INIT(
    0x00,0x76,0x65,0x53,0x00,0x6f,0x69,0x64,0x75,0x41,0x01,0x0a,0x77,0x6f,0x65,0x4d);  /* ..0a01..536576 */
static const ble_uuid128_t meow_audio_uuid = BLE_UUID128_INIT(
    0x00,0x72,0x68,0x43,0x00,0x6f,0x69,0x64,0x75,0x41,0x02,0x0a,0x77,0x6f,0x65,0x4d);  /* ..0a02..436872 */

#define CLIP_SECONDS     5                                /* clip length we slice the stream into */
#define CLIP_RATE        8000                             /* matches the collar (lower quality, smaller) */
#define CLIP_PCM         (CLIP_RATE * 2 * CLIP_SECONDS)   /* mono 16-bit */
#define WAV_HDR          44
#define CLIP_COOLDOWN_MS 0       /* no gap , capture back-to-back while in range */
#define CLIP_RX_TIMEOUT_MS 25000                          /* give up on a clip that never completes */

static uint16_t g_cap_val_handle = 0;
static uint16_t g_cap_conn = 0xffff;       /* active capture connection handle */
static char     g_cap_id[16];
static int64_t  g_last_capture_ms = 0;
static int64_t  g_cap_start_ms = 0;        /* when the current capture connected */
static volatile int64_t g_last_frame_ms = 0; /* last frame received (stall detection) */

/* The collar streams continuously in 100 ms frames, each [hdr][audio PCM][IMU int16] on the audio
 * characteristic (see firmware/collar). We concatenate frames and emit a clip every CLIP_FRAMES
 * (= 5 s). Two clip buffers ping-pong: one fills from the BLE host task while the other uploads from
 * the main task, so we don't miss audio during the upload. */
/* MEOW_CLIP_MAGIC + struct meow_clip_hdr (meow_clip_hdr_t) come from firmware/common/meow_protocol.h,
 * shared with the collar so the wire format can't drift between the two. */
#define CLIP_FRAMES     (CLIP_SECONDS * 10)              /* 100 ms frames per clip = 50 for 5 s */
#define IMU_MAX_BYTES   (110 * CLIP_SECONDS * 6 * 2)     /* IMU int16 per clip, with ODR margin */

enum { BUF_FREE = 0, BUF_FILLING, BUF_READY, BUF_UPLOADING };
typedef struct {
    uint8_t  *wav;          /* WAV_HDR + CLIP_PCM (header reserved at front) */
    uint8_t  *imu;          /* IMU_MAX_BYTES */
    uint32_t  pcm_len;      /* PCM bytes (excludes the reserved header) */
    uint32_t  imu_len;
    int       frames;
    uint16_t  imu_rate;
    uint8_t   imu_axes;
    volatile int state;
} clipbuf_t;
static clipbuf_t g_cb[2];
static int g_fill = -1;     /* buffer the parser is filling, or -1 = no free buffer (dropping) */

/* frame parser state (a frame spans several notifications) */
static uint8_t  g_hdr[sizeof(meow_clip_hdr_t)];
static uint32_t g_hdr_got = 0;
static bool     g_in_frame = false;
static uint32_t g_fr_audio_left = 0, g_fr_imu_left = 0;
static uint16_t g_fr_rate = 0;
static uint8_t  g_fr_axes = 0;
static bool     g_fr_ulaw = false;   /* header version >= 2: audio bytes are 8-bit µ-law, expand to PCM */

/* ulaw_decode() comes from firmware/common/meow_protocol.h (shared with the collar). */

static void wav_header(uint8_t *h, uint32_t pcm, uint32_t rate)
{
    uint32_t chunk = 36 + pcm, byterate = rate * 2;
    memcpy(h, "RIFF", 4);
    h[4]=chunk; h[5]=chunk>>8; h[6]=chunk>>16; h[7]=chunk>>24;
    memcpy(h+8, "WAVEfmt ", 8);
    h[16]=16; h[17]=h[18]=h[19]=0;          /* fmt chunk size */
    h[20]=1; h[21]=0;                        /* PCM */
    h[22]=1; h[23]=0;                        /* mono */
    h[24]=rate; h[25]=rate>>8; h[26]=rate>>16; h[27]=rate>>24;
    h[28]=byterate; h[29]=byterate>>8; h[30]=byterate>>16; h[31]=byterate>>24;
    h[32]=2; h[33]=0;                        /* block align */
    h[34]=16; h[35]=0;                       /* bits/sample */
    memcpy(h+36, "data", 4);
    h[40]=pcm; h[41]=pcm>>8; h[42]=pcm>>16; h[43]=pcm>>24;
}

static void capture_cleanup(bool cooldown)
{
    /* Discard the partially-filled buffer; leave any BUF_READY ones for the main loop to upload. */
    for (int i = 0; i < 2; i++)
        if (g_cb[i].state == BUF_FILLING) g_cb[i].state = BUF_FREE;
    g_fill = -1;
    g_hdr_got = 0; g_in_frame = false;
    g_cap_val_handle = 0; g_cap = CAP_IDLE;
    if (cooldown) g_last_capture_ms = now_ms();
}

/* Claim a FREE clip buffer to fill (called from the BLE host task). Returns its index or -1. */
static int acquire_free(void)
{
    for (int i = 0; i < 2; i++)
        if (g_cb[i].state == BUF_FREE) {
            g_cb[i].pcm_len = 0; g_cb[i].imu_len = 0; g_cb[i].frames = 0;
            g_cb[i].state = BUF_FILLING;
            return i;
        }
    return -1;
}

/* A whole 100 ms frame finished: count it, and at CLIP_FRAMES hand the buffer to the main task. */
static void frame_complete(void)
{
    if (g_fill < 0) return;
    clipbuf_t *b = &g_cb[g_fill];
    b->frames++;
    if (b->frames >= CLIP_FRAMES) {
        b->imu_rate = g_fr_rate; b->imu_axes = g_fr_axes;
        b->state = BUF_READY;          /* main loop uploads it */
        g_fill = acquire_free();       /* ping-pong to the other buffer (or -1 = drop till one frees) */
        if (g_fill < 0) ESP_LOGW(TAG, "no free clip buffer , dropping until an upload finishes");
    }
}

/* Continuous frame parser: header, then audio into the fill buffer's PCM, then IMU into its sidecar.
 * Runs in the BLE host task on each notification; a frame may span several notifications. */
static void feed_stream(const uint8_t *p, uint32_t n)
{
    while (n) {
        if (!g_in_frame) {
            uint32_t need = sizeof g_hdr - g_hdr_got, take = (n < need) ? n : need;
            memcpy(g_hdr + g_hdr_got, p, take); g_hdr_got += take; p += take; n -= take;
            if (g_hdr_got < sizeof g_hdr) return;
            meow_clip_hdr_t *h = (meow_clip_hdr_t *)g_hdr;
            if (h->magic != MEOW_CLIP_MAGIC) {           /* shouldn't happen on a reliable link; resync */
                memmove(g_hdr, g_hdr + 1, sizeof g_hdr - 1); g_hdr_got = sizeof g_hdr - 1;
                continue;
            }
            g_fr_audio_left = h->audio_bytes; g_fr_imu_left = h->imu_bytes;
            g_fr_rate = h->imu_rate_hz; g_fr_axes = h->imu_axes;
            g_fr_ulaw = (h->version >= 2);
            g_hdr_got = 0; g_in_frame = true;
            if (g_fill < 0) g_fill = acquire_free();     /* try to grab a buffer at frame start */
        } else if (g_fr_audio_left) {
            uint32_t take = (n < g_fr_audio_left) ? n : g_fr_audio_left;
            if (g_fill >= 0) {
                clipbuf_t *b = &g_cb[g_fill];
                if (g_fr_ulaw) {
                    /* expand each 8-bit µ-law byte to a 16-bit PCM sample in the WAV buffer */
                    int16_t *out = (int16_t *)(b->wav + WAV_HDR + b->pcm_len);
                    for (uint32_t i = 0; i < take && b->pcm_len + 2 <= CLIP_PCM; i++) {
                        *out++ = ulaw_decode(p[i]); b->pcm_len += 2;
                    }
                } else {
                    uint32_t room = CLIP_PCM - b->pcm_len, t = (take < room) ? take : room;
                    memcpy(b->wav + WAV_HDR + b->pcm_len, p, t); b->pcm_len += t;
                }
            }
            g_fr_audio_left -= take; p += take; n -= take;
        } else if (g_fr_imu_left) {
            uint32_t take = (n < g_fr_imu_left) ? n : g_fr_imu_left;
            if (g_fill >= 0) {
                clipbuf_t *b = &g_cb[g_fill];
                uint32_t room = IMU_MAX_BYTES - b->imu_len, t = (take < room) ? take : room;
                memcpy(b->imu + b->imu_len, p, t); b->imu_len += t;
            }
            g_fr_imu_left -= take; p += take; n -= take;
        }
        if (g_in_frame && g_fr_audio_left == 0 && g_fr_imu_left == 0) {
            g_in_frame = false;
            frame_complete();
        }
    }
}

/* ---- GATT client discovery callbacks ---- */
static int on_subscribe(uint16_t ch, const struct ble_gatt_error *err, struct ble_gatt_attr *attr, void *arg)
{
    if (err->status != 0) { ESP_LOGE(TAG, "subscribe failed (%d)", err->status); ble_gap_terminate(ch, BLE_ERR_REM_USER_CONN_TERM); return 0; }
    g_hdr_got = 0; g_in_frame = false; g_fill = acquire_free();
    g_last_frame_ms = now_ms();
    g_cap = CAP_RECEIVING;
    ESP_LOGI(TAG, "subscribed , streaming");
    return 0;
}
static int on_chr_disc(uint16_t ch, const struct ble_gatt_error *err, const struct ble_gatt_chr *chr, void *arg)
{
    if (err->status == 0 && chr) {
        g_cap_val_handle = chr->val_handle;
        uint8_t en[2] = { 0x01, 0x00 };                 /* enable notifications via the CCCD */
        int rc = ble_gattc_write_flat(ch, chr->val_handle + 1, en, sizeof en, on_subscribe, NULL);
        if (rc) { ESP_LOGE(TAG, "write CCCD rc=%d", rc); ble_gap_terminate(ch, BLE_ERR_REM_USER_CONN_TERM); }
    } else if (err->status == BLE_HS_EDONE && g_cap_val_handle == 0) {
        ESP_LOGE(TAG, "audio characteristic not found");
        ble_gap_terminate(ch, BLE_ERR_REM_USER_CONN_TERM);
    }
    return 0;
}
static int on_svc_disc(uint16_t ch, const struct ble_gatt_error *err, const struct ble_gatt_svc *svc, void *arg)
{
    if (err->status == 0 && svc) {
        int rc = ble_gattc_disc_chrs_by_uuid(ch, svc->start_handle, svc->end_handle,
                                             &meow_audio_uuid.u, on_chr_disc, NULL);
        if (rc) ESP_LOGE(TAG, "disc chrs rc=%d", rc);
    } else if (err->status == BLE_HS_EDONE && g_cap_val_handle == 0 && g_cap == CAP_CONNECTING) {
        /* service-discovery finished with no char yet , on_chr_disc handles "not found" */
    }
    return 0;
}

static int on_mtu(uint16_t conn_handle, const struct ble_gatt_error *error, uint16_t mtu, void *arg)
{
    /* With the default 23-byte MTU each notification carries only 20 bytes, so one audio frame needs
     * ~87 of them , far more than the link can push, and the collar's mic buffer overran (the pop).
     * After this exchange the MTU is ~247, ~12x fewer packets per frame. */
    if (error && error->status) ESP_LOGW(TAG, "MTU exchange failed (status=%d)", error->status);
    else                        ESP_LOGI(TAG, "MTU negotiated: %d", mtu);
    return 0;
}

static int central_gap_cb(struct ble_gap_event *event, void *arg)
{
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            g_cap_val_handle = 0;
            g_cap_conn = event->connect.conn_handle;
            g_cap_start_ms = now_ms();
            ESP_LOGI(TAG, "connected to collar, negotiating MTU + 2M PHY + discovering audio service");
            ble_gattc_exchange_mtu(event->connect.conn_handle, on_mtu, NULL);   /* 23 -> ~247 bytes */
            /* Move to 2M PHY: halves airtime per packet so more fit per connection event, giving the
             * ~17 KB/s audio stream clear headroom (1M sat right at the edge and dropped frames). */
            ble_gap_set_prefered_le_phy(event->connect.conn_handle,
                                        BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_2M_MASK, 0);
            ble_gattc_disc_svc_by_uuid(event->connect.conn_handle, &meow_svc_uuid.u, on_svc_disc, NULL);
        } else {
            ESP_LOGW(TAG, "collar connect failed (%d)", event->connect.status);
            capture_cleanup(true);
            start_scan();
        }
        return 0;
    case BLE_GAP_EVENT_NOTIFY_RX:
        if (g_cap == CAP_RECEIVING) {
            uint16_t plen = OS_MBUF_PKTLEN(event->notify_rx.om);
            uint8_t tmp[256];
            if (plen > sizeof tmp) plen = sizeof tmp;
            os_mbuf_copydata(event->notify_rx.om, 0, plen, tmp);
            feed_stream(tmp, plen);
            g_last_frame_ms = now_ms();
        }
        return 0;
    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "collar disconnected");
        g_cap_conn = 0xffff;
        capture_cleanup(true);   /* drops the partial buffer; any full BUF_READY ones still upload */
        start_scan();
        return 0;
    default:
        return 0;
    }
}

static void start_capture(void)
{
    xSemaphoreTake(g_collar_mtx, portMAX_DELAY);
    ble_addr_t addr = g_near_addr;
    snprintf(g_cap_id, sizeof g_cap_id, "%s", g_near_id);
    xSemaphoreGive(g_collar_mtx);

    g_hdr_got = 0; g_in_frame = false; g_fill = -1;
    g_cap = CAP_CONNECTING;

    ble_gap_disc_cancel();                 /* stop scanning so we can connect */
    /* Explicit connection params , the NimBLE default is a 30-50 ms interval, far too slow to drain
     * the ~17 KB/s audio stream, so the collar's mic buffer overran and the mic restarted (the pop).
     * A short 15 ms interval with a long connection-event budget lets many packets flow per event,
     * giving plenty of headroom over the audio rate. */
    /* The ESP32-S3 only sends ~1 packet per connection event (WiFi/BLE share the radio), so throughput
     * is (packet payload / interval). At 15 ms that capped at ~16 KB/s , just under the audio rate, so
     * frames dropped. Drop to the 7.5 ms BLE minimum to double the event rate (~32 KB/s) and clear the
     * audio rate with margin. (More TX buffers / 2M PHY didn't help , the limiter is packets-per-event.) */
    struct ble_gap_conn_params cp = {
        .scan_itvl = 0x0010, .scan_window = 0x0010,
        .itvl_min = 6, .itvl_max = 6,          /* 6 * 1.25 ms = 7.5 ms (minimum) */
        .latency = 0, .supervision_timeout = 400,   /* 4 s */
        .min_ce_len = 0, .max_ce_len = 0x0100,      /* allow long events = many packets per interval */
    };
    int rc = ble_gap_connect(g_own_addr_type, &addr, 8000, &cp, central_gap_cb, NULL);
    if (rc) { ESP_LOGE(TAG, "ble_gap_connect rc=%d", rc); capture_cleanup(true); start_scan(); }
    else    ESP_LOGI(TAG, "capturing audio from %s", g_cap_id);
}

/* Make a clip audible: remove DC, normalise the loudest peak to ~80% of full scale (capped so a quiet
 * clip isn't blown up into noise), then fade the first/last few ms so there's no edge click. This used
 * to run on the collar per clip; it moved here since the collar now streams without clip boundaries. */
#define NORM_TARGET   26000
#define NORM_MAX_GAIN 32
static void normalize_pcm(int16_t *s, uint32_t n)
{
    if (!n) return;
    int64_t sum = 0;
    for (uint32_t i = 0; i < n; i++) sum += s[i];
    int dc = (int)(sum / n), peak = 1;
    for (uint32_t i = 0; i < n; i++) {
        s[i] -= dc;
        int a = s[i] < 0 ? -s[i] : s[i];
        if (a > peak) peak = a;
    }
    int32_t num = NORM_TARGET, den = peak;
    if (num > den * NORM_MAX_GAIN) { num = NORM_MAX_GAIN; den = 1; }
    for (uint32_t i = 0; i < n; i++) {
        int32_t v = (int32_t)s[i] * num / den;
        s[i] = (v > 32767) ? 32767 : (v < -32768 ? -32768 : (int16_t)v);
    }
    uint32_t fade = (n < 160) ? n / 2 : 80;
    for (uint32_t i = 0; i < fade; i++) {
        s[i]         = (int16_t)((int32_t)s[i]         * (int)i / (int)fade);
        s[n - 1 - i] = (int16_t)((int32_t)s[n - 1 - i] * (int)i / (int)fade);
    }
}

/* Parse the "path" field out of the upload_clip Cloud Function's JSON reply
 * ({"ok":true,"path":"training/<uid>/<collar>/<ts>.<ext>"}) into `out`. Returns true on success. */
static bool parse_upload_path(const char *json, char *out, int out_cap)
{
    if (!json || !json[0]) return false;
    cJSON *j = cJSON_Parse(json);
    if (!j) return false;
    cJSON *p = cJSON_GetObjectItem(j, "path");
    bool ok = cJSON_IsString(p) && p->valuestring;
    if (ok) snprintf(out, out_cap, "%s", p->valuestring);
    cJSON_Delete(j);
    return ok;
}

/* Upload one finished clip: POST the WAV (and paired IMU sidecar) to the authenticated upload_clip
 * Cloud Function, then index the clip in RTDB under /clips/{ts} using the storage paths it returns. */
static void do_upload(clipbuf_t *b)
{
    int64_t ts = now_ms();
    normalize_pcm((int16_t *)(b->wav + WAV_HDR), b->pcm_len / 2);
    wav_header(b->wav, b->pcm_len, CLIP_RATE);

    /* WAV first. The function validates g_token, stores the bytes and returns the storage path. */
    static char url[320], reply[256], wav_path[160];
    snprintf(url, sizeof url, "%s?collar=%s&ts=%lld&ext=wav",
             UPLOAD_CLIP_URL, g_cap_id, (long long)ts);
    int status = http_post_bin(url, b->wav, WAV_HDR + b->pcm_len, "audio/wav", g_token, reply, sizeof reply);
    bool have_wav = (status == 200) && parse_upload_path(reply, wav_path, sizeof wav_path);
    ESP_LOGI(TAG, "upload %s status=%d (%u B) path=%s",
             g_cap_id, status, (unsigned)(WAV_HDR + b->pcm_len), have_wav ? wav_path : "?");

    /* Paired IMU window as a sidecar (raw int16 [ax,ay,az,gx,gy,gz], accel mg + gyro cdps). */
    char imu_path[160];
    bool have_imu = false;
    if (b->imu_len > 0) {
        snprintf(url, sizeof url, "%s?collar=%s&ts=%lld&ext=imu",
                 UPLOAD_CLIP_URL, g_cap_id, (long long)ts);
        int imu_status = http_post_bin(url, b->imu, b->imu_len, "application/octet-stream", g_token, reply, sizeof reply);
        have_imu = (imu_status == 200) && parse_upload_path(reply, imu_path, sizeof imu_path);
        ESP_LOGI(TAG, "imu upload status=%d (%u B) path=%s",
                 imu_status, (unsigned)b->imu_len, have_imu ? imu_path : "?");
    } else {
        /* Clip will land as "audio only" in the dashboard. The collar sent no IMU bytes this clip,
         * which means its imu_drain() returned nothing , check the collar log for "IMU ready". */
        ESP_LOGW(TAG, "clip has NO IMU data (collar sent 0 bytes) , uploading audio only");
    }

    if (have_wav) {
        static char body[700], suffix[48];
        snprintf(suffix, sizeof suffix, "/clips/%lld", (long long)ts);
        if (have_imu) {
            uint8_t axes = b->imu_axes ? b->imu_axes : 6;
            snprintf(body, sizeof body,
                "{\"ts\":%lld,\"collar\":\"%s\",\"durationSec\":%d,\"path\":\"%s\","
                "\"imuPath\":\"%s\",\"imuRateHz\":%d,\"imuAxes\":%d,\"imuFrames\":%u}",
                (long long)ts, g_cap_id, CLIP_SECONDS, wav_path, imu_path,
                b->imu_rate, axes, (unsigned)(b->imu_len / (axes * 2)));
        } else {
            snprintf(body, sizeof body,
                "{\"ts\":%lld,\"collar\":\"%s\",\"durationSec\":%d,\"path\":\"%s\"}",
                (long long)ts, g_cap_id, CLIP_SECONDS, wav_path);
        }
        dev_write(HTTP_METHOD_PUT, suffix, body);
    }
}

void ble_start(void)
{
    g_collar_mtx = xSemaphoreCreateMutex();

    /* Two ping-pong clip buffers in PSRAM (held for the program's life). One fills from the BLE host
     * task while the other uploads from the main task, so streaming never pauses for an upload. */
    for (int i = 0; i < 2; i++) {
        g_cb[i].wav = heap_caps_malloc(WAV_HDR + CLIP_PCM, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        g_cb[i].imu = heap_caps_malloc(IMU_MAX_BYTES,      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!g_cb[i].wav || !g_cb[i].imu) ESP_LOGE(TAG, "clip buffer %d alloc failed", i);
        g_cb[i].state = BUF_FREE;
    }

    esp_err_t e = nimble_port_init();
    if (e != ESP_OK) { ESP_LOGE(TAG, "nimble_port_init failed (%d) , collar relay disabled", e); return; }
    ble_hs_cfg.sync_cb = ble_on_sync;
    nimble_port_freertos_init(ble_host_task);
}

/* Per-tick (~1 s) capture servicing. Owns the capture state machine so main.c stays out of BLE
 * internals: start a capture when triggered, tear it down the instant the trigger clears (otherwise
 * the persistent stream would upload a clip every 5 s forever , the runaway-upload bug), enforce the
 * connect/stall timeouts, and drain any completed clip buffers by uploading them. */
void ble_service(void)
{
    /* Capture when the normal toggle is on AND a registered collar is in range , OR, independently,
     * when manual/force mode is on and a collar is heard at all (any distance). The latter is how
     * we grab purring, since that won't happen at the bowl. Production mode never records: ready
     * stays false, so nothing connects/streams/uploads, and the teardown below stops any capture in
     * flight when the mode is flipped. */
    bool ready = !g_production && ((g_capture_on && g_inrange) || (g_force_capture && g_heard));
    if (ready && g_allow_n > 0 && g_cap == CAP_IDLE &&
        (now_ms() - g_last_capture_ms) > CLIP_COOLDOWN_MS)
        start_capture();
    /* STOP as soon as the trigger clears (capture toggled off, cat left range, or went quiet). Also
     * drop any finished-but-unsent clip so nothing uploads once the trigger is gone (READY buffers
     * aren't touched by the BLE task, so this is safe). */
    if (!ready && (g_cap == CAP_RECEIVING || g_cap == CAP_CONNECTING) && g_cap_conn != 0xffff) {
        ESP_LOGI(TAG, "capture trigger cleared , disconnecting (no more uploads)");
        for (int i = 0; i < 2; i++)
            if (g_cb[i].state == BUF_READY) g_cb[i].state = BUF_FREE;
        ble_gap_terminate(g_cap_conn, BLE_ERR_REM_USER_CONN_TERM);
    }
    /* connecting timeout: abort if BLE connect never establishes */
    if (g_cap == CAP_CONNECTING && g_cap_conn != 0xffff &&
        (now_ms() - g_cap_start_ms) > CLIP_RX_TIMEOUT_MS) {
        ESP_LOGW(TAG, "BLE connect timeout, aborting");
        ble_gap_terminate(g_cap_conn, BLE_ERR_REM_USER_CONN_TERM);
    }
    /* frame stall: connected and streaming but no frame for too long — reconnect */
    if (g_cap == CAP_RECEIVING && g_cap_conn != 0xffff &&
        (now_ms() - g_last_frame_ms) > CLIP_RX_TIMEOUT_MS) {
        ESP_LOGW(TAG, "frame stall, reconnecting");
        ble_gap_terminate(g_cap_conn, BLE_ERR_REM_USER_CONN_TERM);
    }
    /* upload any completed clip buffers from the main task (ping-pong) */
    for (int i = 0; i < 2; i++) {
        if (g_cb[i].state == BUF_READY) {
            g_cb[i].state = BUF_UPLOADING;
            do_upload(&g_cb[i]);
            g_cb[i].state = BUF_FREE;
        }
    }
}
