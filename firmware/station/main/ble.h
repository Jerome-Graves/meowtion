#pragma once
#include <stdbool.h>
#include <stdint.h>
/* ble.h , NimBLE collar subsystem: scan/relay + audio capture, fully encapsulated.
 *
 * main.c drives this through these calls only and never touches BLE internals: the scan table,
 * the capture state machine, and the clip buffers all live inside ble.c. ble_service() runs the
 * per-tick capture work (start/stop, timeouts, uploads); the rest are the periodic publishers. */

void ble_start(void);          /* init NimBLE host + clip buffers; begin scanning for collars */

void ble_relay(void);          /* relay fresh, registered collars to /cats/{id} (incl. proximity + rssi) */
void ble_publish_seen(void);   /* advertise heard-but-unregistered collars to /seen */
void ble_fetch_allow(void);    /* refresh the registered-collar allow-list (the gate) */
void ble_fetch_config(void);   /* refresh capture toggle + range settings from /config */
void ble_heartbeat(void);      /* station presence + power + registered-collar count */

void ble_service(void);        /* per-tick (~1 s): drive capture start/stop, timeouts, uploads */

int  ble_allowed_count(void);  /* number of registered collars (gate count) */

/* ---- OTA support (used by ota.c) ----
 * The OTA push needs to connect to the same collar the relay/capture path hears, and must not
 * fight the audio-capture connection for the radio. These expose just enough for ota.c to do that
 * without reaching into ble.c internals. */
bool ble_capture_active(void);                 /* true while a capture connection is up/connecting */
bool ble_near_collar_addr(void *out_ble_addr); /* copy the in-range collar's addr (ble_addr_t*); false if none fresh */
uint8_t ble_own_addr_type(void);               /* our resolved BLE address type (for connect) */
void ble_resume_scan(void);                    /* resume the observer scan after an OTA connect (idempotent) */
