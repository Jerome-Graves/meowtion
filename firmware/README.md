# Firmware

Two devices that share one BLE wire format.

| Dir | Device | Stack | Role |
|-----|--------|-------|------|
| [`collar/`](collar/README.md) | Seeed XIAO nRF52840 Sense | Zephyr / nRF Connect SDK | On the cat. BLE-only: senses, advertises telemetry, and streams paired audio + IMU clips for training. |
| [`station/`](station/README.md) | Seeed XIAO ESP32-S3 | ESP-IDF | By the bowl. BLE central + WiFi gateway: relays the collar to Firebase and uploads training clips. |
| [`common/`](common/) | shared | C header | `meow_protocol.h`: the BLE clip-frame wire format + µ-law codec, included by both so the format can't drift. |

## How they fit together

```
collar  --BLE-->  station  --HTTPS-->  Firebase  -->  dashboard
```

The collar is Bluetooth-only and battery-powered, so the always-on, mains-powered station is its
gateway to the cloud. In **training** mode the collar streams audio + IMU clips and the station
uploads them; in **production** mode the collar classifies on-device and the station relays only
the result. System overview: the root [README](../README.md).

## Build

- **Collar** (Zephyr): `./build.ps1` , wraps `west` / the NCS toolchain. See [collar/README.md](collar/README.md).
- **Station** (ESP-IDF): `idf.py build`. See [station/README.md](station/README.md).

Both are verified building (collar on NCS v3.3.1; station on ESP-IDF).
