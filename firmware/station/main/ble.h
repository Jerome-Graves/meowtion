#pragma once
/* ble.h , NimBLE collar subsystem: scan/relay + audio capture, fully encapsulated.
 *
 * main.c drives this through these calls only and never touches BLE internals: the scan table,
 * the capture state machine, and the clip buffers all live inside ble.c. ble_service() runs the
 * per-tick capture work (start/stop, timeouts, uploads); the rest are the periodic publishers. */

void ble_start(void);          /* init NimBLE host + clip buffers; begin scanning for collars */

void ble_relay(void);          /* relay fresh, registered collars to /cats/{id} */
void ble_publish_dev(void);    /* live proximity status (signal/state) to /dev */
void ble_publish_seen(void);   /* advertise heard-but-unregistered collars to /seen */
void ble_fetch_allow(void);    /* refresh the registered-collar allow-list (the gate) */
void ble_fetch_config(void);   /* refresh capture toggle + range settings from /config */
void ble_heartbeat(void);      /* station presence + power + registered-collar count */

void ble_service(void);        /* per-tick (~1 s): drive capture start/stop, timeouts, uploads */

int  ble_allowed_count(void);  /* number of registered collars (gate count) */
