# Station firmware (ESP32-S3, ESP-IDF)

The base station. A **BLE central** that hears registered collars and a **WiFi gateway** that
relays them to the owner's Firebase account. It also captures short audio + IMU clips for training
and uploads them through the authenticated `upload_clip` Cloud Function.

No Firebase login: WiFi + owner + a per-device **token** are provisioned over USB serial and stored
in NVS. The database rules authorise the device because the token is registered to that owner
(`deviceTokens/<token>/owner`); delete the token to revoke.

## Modules (`main/`)

| File | Responsibility |
|------|----------------|
| `main.c` | boot + the ~1 s orchestration loop |
| `config.c` | provisioned creds, NVS, USB-serial provisioning |
| `board.c` | power source (USB vs battery) |
| `wifi.c` | STA bring-up + time sync |
| `cloud.c` | the Firebase RTDB / HTTP layer (the only HTTP) |
| `weather.c` | Open-Meteo feed |
| `ble.c` | the whole NimBLE collar subsystem (scan/relay + audio capture), behind `ble_service()` |
| `ota.c` | OTA model delivery: pushes trained `.tflite` models to the collar over BLE |

## Clip upload

Captured clips are POSTed to the `upload_clip` Cloud Function with the device token; the function
verifies the token's owner and writes the file to that owner's Storage area (clients cannot write
Storage directly). The station records the returned Storage path under `/clips`. See
[`../../app/firebase/README.md`](../../app/firebase/README.md).

## OTA model delivery

The station also delivers trained models to the collar over BLE (Phase 3 of the model pipeline).
The shared wire protocol is fixed in [`../common/meow_ota.h`](../common/meow_ota.h): the collar is the
GATT server that stages a `.tflite` into flash, the station is the client that pushes it.

- **Version gate.** The `train` Cloud Function bumps `users/<uid>/models/version` and mirrors it into
  this station's own config as `modelVer` (the station can read only its own
  `users/<uid>/devices/<token>/` subtree, not `users/<uid>/models`). The station reads `config/modelVer`,
  keeps its own last-pushed version in NVS, and a push is due when the config version is higher.
- **Download.** For each slot it GETs the model from Storage at the public-read path
  `models/<uid>/imu_model.tflite` (IMU slot) and `models/<uid>/audio_model.tflite` (audio slot). A 404
  just means that slot has no model yet and is skipped.
- **Push.** It computes a CRC-32/IEEE over the bytes (matching the collar's `crc32_ieee`), then over a
  brief dedicated BLE connection writes `BEGIN`, streams the model to the DATA characteristic in
  `(MTU-3)` write-with-response chunks (the collar's flash-write flow control), and writes `END`. On
  the collar's `OK` it records the new version in NVS; on any error it leaves NVS unchanged and retries.

A push runs only when a registered collar is in range and audio capture is idle, so it never contends
with the capture/relay path for the radio.

## Build & flash

```
. $env:USERPROFILE\esp\esp-idf\export.ps1
idf.py build
idf.py -p <COM> flash monitor
```

(The repo's VS Code task **Build+Flash Station** wraps this.) Verified building with ESP-IDF.

## Provisioning

Send a JSON line over USB serial (the dashboard's "Connect a device" form does this automatically):

```
{"ssid":"..","pass":"..","owner":"<uid>","token":"<random>","name":"..","lat":50.8,"lon":-0.1}
```

Re-provision any time from the dashboard, or wipe with `idf.py erase-flash`.
