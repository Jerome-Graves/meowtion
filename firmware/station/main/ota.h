#pragma once
/*
 * ota.h , OTA model delivery: the station side that pushes trained models to the collar.
 *
 * main.c / ble.c drive this through these calls only. The push is gated on a model version the
 * cloud bumps in RTDB (models/<owner>/ver); the actual BLE transfer runs over the same kind of
 * NimBLE central connection ble.c uses for audio capture (see ota.c for the full flow). */

#include <stdbool.h>
#include <stdint.h>

/* True if the cloud has published a newer model than this station last pushed: RTDB
 * models/<owner>/ver (missing == 0) is greater than the NVS last-pushed version. Polled
 * cheaply from the main loop; does no BLE work. */
bool ota_push_due(void);

/* Run one full OTA push to the already-connected collar `conn_handle`: for each slot that has a
 * model in Storage, download it, CRC it, and stream it over the OTA GATT service. Blocks the
 * caller (the BLE task / service loop) until done or timed out. On a fully successful push it
 * records the new version in NVS so ota_push_due() goes quiet until the cloud bumps it again.
 * Returns true if at least one slot was delivered OK. Safe to call only with a live connection. */
bool ota_run_push(uint16_t conn_handle);
