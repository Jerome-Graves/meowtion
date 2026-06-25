/*
 * Collar-side OTA model delivery (Phase 3). See ota.c for the full design.
 *
 * Two entry points:
 *   - The OTA GATT service self-registers via BT_GATT_SERVICE_DEFINE in ota.c , no init call needed,
 *     it is live as soon as bt_enable() runs.
 *   - ota_load_stored_models() is the boot-time path: it scans the flash model slots and, for any
 *     slot with a valid header + matching CRC, hands the in-flash model to the classifier. Call it
 *     once at boot (after clf_init()) so a previously-OTA'd model is live immediately, independent
 *     of any station connection.
 */
#pragma once

/* Scan both flash model slots; load any valid (header + CRC checked) model into the classifier.
 * Pure flash + classifier , no Bluetooth involved. Safe to call before bt_enable(). */
void ota_load_stored_models(void);
