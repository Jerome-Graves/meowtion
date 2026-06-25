# Collar firmware (nRF52840, Zephyr)

The cat collar. **BLE-only** , it senses on the cat and runs one **connectable** advertisement
carrying an 8-byte telemetry packet plus a custom audio service. When the station connects and
subscribes, the collar streams paired audio + IMU in 100 ms frames for training capture. It never
touches WiFi/internet, which keeps it tiny and low-power, and it always runs on its own battery.

## Modules (`src/`)

| File | Responsibility |
|------|----------------|
| `main.c` | boot + the telemetry loop (orchestration only) |
| `ble.c` | advertising, identity, the audio GATT service, notify |
| `audio.c` | PDM mic capture -> 8 kHz µ-law |
| `streaming.c` | the decoupled reader/sender threads that assemble + send frames |
| `battery.c` | 1S LiPo charge via the onboard divider |
| `imu.c` | LSM6DS3TR-C continuous sampler |
| `classifier.c` | the confidence-gated action cascade (weak stubs until a model lands) |
| `audio_codec.h` | µ-law + the model-input audio representation |

## Telemetry packet (manufacturer AD data, 8 bytes)

| bytes | field |
|-------|-------|
| 0-1 | company id (`0xFFFF`, test) |
| 2 | version |
| 3 | state (0 sleep, 1 rest, 2 active, 3 walk, 4 play, 5 groom) |
| 4 | activity (0-100) |
| 5-6 | steps (uint16, little-endian) |
| 7 | battery (0-100) |

The collar's BLE address identifies which collar it is, so no id goes in the payload.

## On-device AI , Phase-1 scaffold

The telemetry state/activity/steps are currently **simulated** (a dwell-based behaviour state
machine; real battery is wired). This is a placeholder for the trained classifier: once a model is
dropped into `classifier.c` (today weak stubs), real IMU + audio classification replaces the
simulation. The cascade already runs at capture time in `streaming.c` on the IMU window paired with
each clip. See the root [README](../../README.md) for the model + OTA plan.

## Build & flash

```
./build.ps1
```

`build.ps1` finds the local NCS toolchain itself, runs `west build -b xiao_ble`, and copies the
UF2. The XIAO nRF52840 has **no debug COM port** for flashing , flashing is always **UF2
drive-copy**: double-tap RESET so the board mounts as a USB drive, then re-run (the script copies
the UF2 across). Artifact: `build/collar/zephyr/zephyr.uf2`. Verified with **NCS v3.3.1**.

Console note: the firmware uses the **legacy** USB device stack (`CONFIG_USB_DEVICE_STACK` +
`CONFIG_USB_CDC_ACM`) and calls `usb_enable()`, because the new (NEXT) stack's CDC console silently
drops output on this board. Keep exactly one `zephyr,cdc-acm-uart` node.

## Watching it run

Open the CDC serial port (any baud) , `MEOW> collar id=cat_xxxxxx` and `state= steps= batt=` print
every 2 s. The port only appears once the app is running (not in the UF2 bootloader). That
`MEOW> collar id=` line is what the dashboard reads over Web Serial to register the collar.
