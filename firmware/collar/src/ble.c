/*
 * BLE link , advertising, identity, and the audio GATT service. See ble.h.
 *
 * One connectable advertisement carries the telemetry packet AND exposes a custom audio service.
 * advertising auto-stops while connected and the main loop resumes it on disconnect (restarting it
 * from the disconnect callback is unreliable).
 */
#include "ble.h"

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/sys/util.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(ble, LOG_LEVEL_INF);

#define COMPANY_ID 0xFFFF        /* SIG test/"no company" id */

/* Telemetry packet (manufacturer-specific AD data, 8 bytes). main() fills [3..7] each cycle. */
static uint8_t mfg[8] = { COMPANY_ID & 0xFF, (COMPANY_ID >> 8) & 0xFF, 1, 1, 0, 0, 0, 96 };

/* Identity the dashboard registers and the station relays. Derived from the BLE address the
 * SAME way the station does (cat_<addr[2]><addr[1]><addr[0]>), so the two always agree. */
static char g_id[16] = "cat_000000";

void ble_compute_id(void)
{
    bt_addr_le_t addrs[CONFIG_BT_ID_MAX];
    size_t count = ARRAY_SIZE(addrs);
    bt_id_get(addrs, &count);
    if (count > 0) {
        const uint8_t *v = addrs[0].a.val;     /* little-endian */
        snprintk(g_id, sizeof g_id, "cat_%02x%02x%02x", v[2], v[1], v[0]);
    }
}

const char *ble_id(void) { return g_id; }

uint8_t *ble_mfg_data(void) { return mfg; }

static struct bt_data ad[] = {
    BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_NO_BREDR),
    BT_DATA(BT_DATA_MANUFACTURER_DATA, mfg, sizeof(mfg)),
};

/* ---------------- BLE audio service (stream the mic when a central connects) ----------------
 * Custom 128-bit service with one NOTIFY characteristic. When a central (the station, or a phone
 * for testing) connects and enables notifications, the stream thread sends µ-law audio frames as
 * notifications. The collar keeps a CONNECTABLE advert carrying the telemetry packet (identity
 * address, so the id stays stable); advertising auto-stops while connected and resumes on disconnect. */
#define MEOW_SVC_UUID   BT_UUID_128_ENCODE(0x4d656f77, 0x0a01, 0x4175, 0x6469, 0x6f0053657600)
#define MEOW_AUDIO_UUID BT_UUID_128_ENCODE(0x4d656f77, 0x0a02, 0x4175, 0x6469, 0x6f0043687200)
static struct bt_uuid_128 meow_svc_uuid   = BT_UUID_INIT_128(MEOW_SVC_UUID);
static struct bt_uuid_128 meow_audio_uuid = BT_UUID_INIT_128(MEOW_AUDIO_UUID);

static volatile bool   g_streaming = false;
static struct bt_conn *g_conn = NULL;

static void audio_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
    ARG_UNUSED(attr);
    g_streaming = (value == BT_GATT_CCC_NOTIFY);
    LOG_INF("audio notifications %s", g_streaming ? "ON" : "off");
}

BT_GATT_SERVICE_DEFINE(meow_audio_svc,
    BT_GATT_PRIMARY_SERVICE(&meow_svc_uuid),
    BT_GATT_CHARACTERISTIC(&meow_audio_uuid.uuid, BT_GATT_CHRC_NOTIFY,
                           BT_GATT_PERM_NONE, NULL, NULL, NULL),
    BT_GATT_CCC(audio_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
);

static const struct bt_le_adv_param adv_param = BT_LE_ADV_PARAM_INIT(
    BT_LE_ADV_OPT_CONN | BT_LE_ADV_OPT_USE_IDENTITY,   /* connectable, keep the identity address */
    BT_GAP_ADV_FAST_INT_MIN_2, BT_GAP_ADV_FAST_INT_MAX_2, NULL);

void ble_start_adv(void)
{
    int err = bt_le_adv_start(&adv_param, ad, ARRAY_SIZE(ad), NULL, 0);
    if (err && err != -EALREADY) LOG_ERR("adv start failed (%d)", err);   /* -EALREADY = already on */
}

void ble_update_adv(void)
{
    bt_le_adv_update_data(ad, ARRAY_SIZE(ad), NULL, 0);
}

bool ble_is_connected(void)    { return g_conn != NULL; }
bool ble_streaming_enabled(void) { return g_streaming; }

static void on_connected(struct bt_conn *conn, uint8_t err)
{
    if (err) { LOG_ERR("connect failed (0x%02x)", err); return; }
    g_conn = bt_conn_ref(conn);
    LOG_INF("central connected");
}
static void on_disconnected(struct bt_conn *conn, uint8_t reason)
{
    ARG_UNUSED(conn);
    LOG_INF("central disconnected (0x%02x)", reason);
    g_streaming = false;
    if (g_conn) { bt_conn_unref(g_conn); g_conn = NULL; }
    /* don't restart advertising here , doing it inside the disconnect callback is unreliable.
     * The main loop re-starts it (it ensures advertising whenever we're not connected). */
}
BT_CONN_CB_DEFINE(conn_cbs) = { .connected = on_connected, .disconnected = on_disconnected };

/* MTU-chunked notify of an arbitrary buffer on the audio characteristic. Returns 0 when the whole
 * buffer went out, or stops early (non-zero) if the central unsubscribed / disconnected. */
int ble_notify_frame(const uint8_t *p, uint32_t left)
{
    while (left > 0 && g_streaming) {
        uint16_t mtu = g_conn ? bt_gatt_get_mtu(g_conn) : 23;
        uint16_t chunk = (mtu > 3) ? (uint16_t)(mtu - 3) : 20;
        uint16_t n = (left < chunk) ? (uint16_t)left : chunk;
        int err = bt_gatt_notify(NULL, &meow_audio_svc.attrs[1], p, n);
        if (err == -ENOMEM || err == -EAGAIN || err == -ENOBUFS) { k_sleep(K_MSEC(2)); continue; }
        if (err) return err;             /* unsubscribed / disconnected */
        p += n; left -= n;
    }
    return (left == 0) ? 0 : -ECONNRESET;
}
