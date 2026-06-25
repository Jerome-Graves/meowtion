/*
 * BLE link , advertising, identity, and the audio GATT service.
 *
 * The collar runs ONE connectable advertisement that carries the telemetry packet (manufacturer
 * AD data) plus a custom 128-bit audio service with a single NOTIFY characteristic. A central (the
 * station, or a phone for testing) connects and subscribes; the streaming module then pushes audio
 * frames out through ble_notify_frame(). This module owns everything BLE: identity, the advert,
 * the service, the connection callbacks, and the MTU-chunked notify.
 */
#pragma once
#include <stdint.h>
#include <stdbool.h>

/* Compute the stable collar identity (cat_<addr[2]><addr[1]><addr[0]>) from the BLE address, the
 * SAME way the station derives it, so the two always agree. Call after bt_enable(). */
void ble_compute_id(void);

/* The collar identity string, e.g. "cat_a1b2c3". Valid after ble_compute_id(). */
const char *ble_id(void);

/* Start the connectable advert (telemetry beacon + audio service). Idempotent (-EALREADY is fine). */
void ble_start_adv(void);

/* Refresh the advertised manufacturer AD data after the telemetry bytes change. */
void ble_update_adv(void);

/* True while a central is connected (advertising auto-stops while connected). */
bool ble_is_connected(void);

/* True while the central has notifications enabled, i.e. audio streaming is requested. */
bool ble_streaming_enabled(void);

/* The 8-byte manufacturer telemetry payload the advert carries. main writes into it each cycle:
 *   [0..1] company id   [2] version   [3] state   [4] activity   [5..6] steps LE   [7] battery */
uint8_t *ble_mfg_data(void);

/* MTU-chunked notify of one frame on the audio characteristic. Returns 0 when the whole buffer went
 * out, or non-zero if the central unsubscribed / disconnected partway. */
int ble_notify_frame(const uint8_t *p, uint32_t len);
