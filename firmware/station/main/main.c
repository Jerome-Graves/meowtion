/*
 * Meowtion station firmware (ESP-IDF, Seeed XIAO ESP32-S3).
 *
 * The Meowtion base station: it relays the cat collar's BLE telemetry to the owner's Firebase
 * account and captures short audio + IMU clips for training. No Firebase login , WiFi, owner, and
 * a per-device TOKEN are provisioned over USB serial and stored in NVS. The device writes to
 * /users/{owner}/devices/{token}/... over HTTPS; the database rule allows it because the token is
 * registered to that owner (deviceTokens[token].owner == owner). Delete the token to revoke.
 *
 * On boot it loads NVS (or waits for serial provisioning), joins WiFi, syncs time, marks itself
 * online, then runs a ~1 s loop: relay registered collars, publish proximity, service audio
 * capture, and poll weather.
 *
 * This file owns only orchestration; each subsystem lives in its own module:
 *   config  , provisioned creds + NVS + USB-serial provisioning + shared helpers
 *   board   , power source (USB vs battery)
 *   wifi    , STA bring-up + time sync
 *   cloud   , the Firebase RTDB / HTTP layer (the only HTTP)
 *   weather , Open-Meteo feed
 *   ble     , the whole NimBLE collar subsystem (scan/relay + audio capture)
 *
 * Provisioning JSON (sent by the dashboard's Connect form, or paste into the monitor):
 *   {"ssid":"..","pass":"..","owner":"<uid>","token":"<random>","name":"..","lat":50.8,"lon":-0.1}
 * Re-provision with `idf.py erase-flash`.
 */
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "driver/usb_serial_jtag.h"

#include "config.h"
#include "board.h"
#include "wifi.h"
#include "weather.h"
#include "ble.h"
#include "ota.h"

static const char *TAG = "meowtion";

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    usb_serial_jtag_driver_config_t ujc = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    usb_serial_jtag_driver_install(&ujc);

    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(g_device_id, sizeof g_device_id, "%02x%02x%02x%02x%02x%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    printf("MEOW> meowtion id=%s boot\n", g_device_id);

    if (!nvs_load()) provision_mode();
    ESP_LOGI(TAG, "owner %s, token %.8s..., \"%s\"", g_owner, g_token, g_name);

    if (!wifi_init_sta()) {
        /* Couldn't get on WiFi (likely wrong credentials saved at pairing). Don't block forever:
         * the driver keeps retrying in the background, and meanwhile we listen for a fresh
         * provisioning line over USB so the dashboard can fix the credentials without an
         * erase-flash. (wifi_init_sta already ran once , do NOT call it again, that re-inits the
         * driver and aborts.) */
        ESP_LOGW(TAG, "WiFi connect failed , awaiting re-provisioning over serial");
        char pline[512];
        while (!(xEventGroupGetBits(s_wifi_eg) & WIFI_CONNECTED_BIT)) {
            printf("MEOW> meowtion id=%s awaiting-provisioning\n", g_device_id);
            if (serial_read_line(pline, sizeof pline, 5000) > 0 && try_provision(pline)) {
                ESP_LOGW(TAG, "re-provisioned , restarting");
                vTaskDelay(pdMS_TO_TICKS(300));
                esp_restart();
            }
        }
        ESP_LOGI(TAG, "WiFi recovered");
    }
    wait_for_time();
    power_init();
    ble_start();                 /* scan for collars; only registered ones are relayed */
    ble_fetch_allow();           /* load the registered-collar allow-list (the gate) */
    ble_fetch_config();          /* load the capture-range settings (rssiThreshold, dwellMs) */

    /* Presence is derived from freshness (the station's lastSeen heartbeat + each cat's
     * current.ts), so a device that loses power just stops heartbeating and reads offline. */

    char line[512];
    int tick = 0;
    /* The loop ticks every ~1 s so ble_service() drains BUF_READY clips promptly: a 5 s clip
     * completes every 5 s, and with only two ping-pong buffers, a slow uploader would let both fill
     * and force the frame parser to drop audio. The Firebase-write-heavy calls (heartbeat, relay,
     * publish, config/allow/weather polls) are gated on tick multiples so their cadence is unchanged. */
    while (1) {
        if (tick % 10 == 0) {
            /* Allow re-pairing from the dashboard at any time: announce ourselves, and if a new
             * provisioning line arrives (after the device was disconnected and re-added), adopt
             * the new token and restart cleanly. */
            printf("MEOW> meowtion id=%s\n", g_device_id);
            if (serial_read_line(line, sizeof line, 200) > 0 && try_provision(line)) {
                ESP_LOGW(TAG, "re-provisioned , restarting");
                vTaskDelay(pdMS_TO_TICKS(300));
                esp_restart();
            }
            ble_heartbeat();          /* station presence + power + registered-collar count */
            ble_relay();              /* relays only registered collars (the gate) */
            ble_publish_seen();       /* advertise heard-but-unregistered collars for the dashboard */
            ble_publish_dev();        /* live proximity status (signal/state) for the dev view */
            ble_fetch_config();       /* poll capture toggle + range (~10 s) */
        }
        if (tick % 60 == 0) ble_fetch_allow();                            /* refresh allow-list (~60 s) */
        if (ble_allowed_count() > 0 && tick % 900 == 0) poll_weather();   /* data only once a collar is registered */

        ble_service();   /* serviced every tick (~1 s) so the clip buffers never back up */

        /* OTA model delivery (Phase 3): when the cloud has published a newer model than we last
         * pushed AND a registered collar is in range AND audio capture is idle (so OTA and capture
         * never share the radio), run a blocking push to the collar. Checked on a slow cadence
         * (~30 s) so the RTDB ver poll is cheap; ota_run_push has its own per-step timeouts so a
         * stalled transfer can't wedge the loop. NVS only advances on a clean push, so a failed one
         * simply retries next window. */
        if (tick % 30 == 0 && ble_allowed_count() > 0 && !ble_capture_active() && ota_push_due())
            ota_run_push(0);

        tick++;
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
