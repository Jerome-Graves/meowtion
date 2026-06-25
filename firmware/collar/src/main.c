/*
 * Meowtion collar firmware (Zephyr / nRF Connect SDK, XIAO nRF52840 Sense).
 *
 * The collar is BLE-only: it senses on the cat and runs ONE connectable advertisement carrying a
 * small telemetry packet plus a custom audio service. A station (ESP32) reads the telemetry and,
 * when it connects + subscribes, the collar streams paired audio + IMU for training-data capture.
 * The collar never touches WiFi/internet , that keeps it tiny and low-power.
 *
 * Module split:
 *   ble.c        advertising, identity, the audio GATT service, notify
 *   audio.c      PDM mic capture -> 8 kHz µ-law
 *   streaming.c  the decoupled reader/sender threads that assemble + send frames
 *   battery.c    1S LiPo charge via the onboard divider
 *   imu.c        LSM6DS3TR-C continuous sampler   (unchanged)
 *   classifier.c the confidence-gated action cascade (weak stubs until a model lands; unchanged)
 *
 * Telemetry packet (manufacturer-specific AD data, 8 bytes):
 *   [0..1] company id (0xFFFF, test)   [2] version   [3] state (0..5)
 *   [4] activity (0..100)   [5..6] steps (uint16 LE)   [7] battery (0..100)
 * The collar's BLE address identifies which collar it is (no id needed in the payload).
 *
 * PHASE-1 SCAFFOLD: update_telemetry() below fills the packet with SIMULATED state/activity/steps
 * (real battery is already wired). This is a placeholder for the trained classifier: once a model
 * is dropped into classifier.c (today weak stubs), real IMU + audio classification replaces the
 * simulated state machine and feeds eat/drink/purr into the telemetry.
 */
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/random/random.h>
#include <zephyr/logging/log.h>
#include <zephyr/usb/usb_device.h>
#include <zephyr/drivers/uart.h>

#include "ble.h"
#include "audio.h"
#include "battery.h"
#include "imu.h"
#include "classifier.h"

LOG_MODULE_REGISTER(collar, LOG_LEVEL_INF);

/* state: 0 sleep, 1 rest, 2 active, 3 walk, 4 play, 5 groom */
static uint8_t  g_state = 1;
static uint16_t g_steps = 0;
static uint8_t  g_battery = 96;
static int64_t  g_state_until = 0;       /* uptime (ms) at which the current state ends */

/* per-state dwell range (seconds) and a typical activity level (0..100). A cat holds a
 * behaviour for a realistic spell instead of flickering every packet, so the station relays
 * sensible episodes. (Placeholder until real IMU classification.) */
static const uint16_t DUR_MIN[6] = {  60, 40, 20, 20, 20, 20 };
static const uint16_t DUR_MAX[6] = { 180, 120, 60, 40, 50, 40 };
static const uint8_t  ACT[6]     = {   2, 12, 55, 45, 80, 30 };

/* PHASE-1 SCAFFOLD: simulated behaviour. Real IMU-based classification + step counting (LSM6DS3,
 * via classifier.c) replaces this once a model is trained , the cascade already runs at capture
 * time in streaming.c on the IMU window paired with each audio clip. */
static void update_telemetry(void)
{
    /* TODO: replace with real IMU-based classification + step counting (LSM6DS3). */
    int64_t now = k_uptime_get();

    /* hold each behaviour for a realistic dwell, then transition to a new one */
    if (now >= g_state_until) {
        g_state = sys_rand32_get() % 6;
        uint32_t secs = DUR_MIN[g_state] + (sys_rand32_get() % (DUR_MAX[g_state] - DUR_MIN[g_state] + 1));
        g_state_until = now + (int64_t)secs * 1000;
    }

    if (g_state >= 2 && g_state <= 4) {              /* moving: steps accrue */
        g_steps += 1 + sys_rand32_get() % 4;
    }
    g_battery = read_battery();          /* real pack charge (rises on USB charge) */

    int act = (int)ACT[g_state] + ((int)(sys_rand32_get() % 11) - 5);   /* jitter +/-5 */
    if (act < 0) act = 0; else if (act > 100) act = 100;

    uint8_t *mfg = ble_mfg_data();
    mfg[3] = g_state;
    mfg[4] = (uint8_t)act;
    mfg[5] = g_steps & 0xFF;
    mfg[6] = (g_steps >> 8) & 0xFF;
    mfg[7] = g_battery;
}

int main(void)
{
    /* Bring up USB so the CDC ACM console (the COM port) works, then wait up to ~3 s for a
     * serial terminal to attach (DTR) so boot logs aren't lost. We never block forever , the
     * collar must advertise even with no USB host attached. */
    if (usb_enable(NULL) == 0) {
        const struct device *con = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));
        uint32_t dtr = 0;
        for (int i = 0; i < 30 && !dtr; i++) {
            uart_line_ctrl_get(con, UART_LINE_CTRL_DTR, &dtr);
            k_sleep(K_MSEC(100));
        }
    }

    battery_init();
    audio_mic_init();
    clf_init();                  /* action-classifier cascade (runs model-free until models land) */
    if (!imu_init())             /* LSM6DS3TR-C; sampled alongside each clip + fed to the cascade */
        LOG_ERR("IMU init FAILED , clips will upload audio-only (no paired motion data)");

    int err = bt_enable(NULL);
    if (err) {
        LOG_ERR("bt_enable failed (%d)", err);
        return 0;
    }

    ble_compute_id();
    ble_start_adv();             /* connectable: telemetry beacon + audio service */
    LOG_INF("collar advertising (connectable), id=%s", ble_id());

    while (1) {
        update_telemetry();
        /* (The classifier cascade now runs at capture time in streaming.c, on the IMU window that
         * pairs with each audio clip. A future always-on path would also run it here on a rolling
         * IMU window, gated by wake-on-motion, with eat/drink/purr mapped into the telemetry.) */

        /* Ensure we're advertising whenever not connected. This self-heals the re-advertise after
         * a capture disconnects (restarting adv from the disconnect callback is unreliable), so the
         * station can reconnect for the next clip. While connected, advertising is off , skip it. */
        if (!ble_is_connected()) {
            ble_start_adv();
            ble_update_adv();
        }
        /* Identity banner the dashboard reads over USB serial to register this collar. */
        printk("MEOW> collar id=%s\n", ble_id());
        LOG_INF("state=%u steps=%u batt=%u stream=%d",
                g_state, g_steps, g_battery, ble_streaming_enabled());
        k_sleep(K_SECONDS(2));   /* TODO: wake-on-motion deep sleep for battery life */
    }
    return 0;
}
