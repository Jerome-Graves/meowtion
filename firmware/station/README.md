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

## Clip upload

Captured clips are POSTed to the `upload_clip` Cloud Function with the device token; the function
verifies the token's owner and writes the file to that owner's Storage area (clients cannot write
Storage directly). The station records the returned Storage path under `/clips`. See
[`../../app/firebase/README.md`](../../app/firebase/README.md).

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
