# Testing

Automated unit tests cover the pure, high-value logic in each component. They run with
[pytest](https://pytest.org) and need no cloud credentials or hardware.

## Setup

```bash
python -m pip install -r requirements-dev.txt   # pytest (the test runner)
```

The dashboard tests also need `pandas` and the cloud-function tests need `numpy`; both are
already listed in those components' own requirements.

## Run

```bash
python -m pytest app/dashboard/tests app/firebase/functions/tests
```

## What is covered

- **`app/dashboard/tests/test_data.py`** , the dashboard data layer (`meowtion_dash/data.py`):
  raw-event to DataFrame conversion, model-label resolution by class index, the low-power
  **rest** event handling (class byte `0xFE` falls back to the `rest` type instead of indexing
  the label list), activity filtering, and the over-time duration aggregation. Malformed events
  (missing timestamp) are skipped.
- **`app/firebase/functions/tests/test_dsp.py`** , the cloud trainer's signal helpers
  (`main.py`): per-window normalisation (the exact representation the collar must reproduce at
  inference, so this is a core cascade-correctness property) and the overlapping-window framing,
  including short-input zero-padding. The Firebase SDKs are stubbed (see `conftest.py`) so the
  helpers test in isolation.

## Firmware (collar, C)

The on-device cascade logic is pure C, so it is unit-tested on the host (no Zephyr, no hardware)
under `firmware/test/`:

- **`test_activity.c`** , the rules-based activity gate (`activity.c`): motion keeps the collar
  awake, sustained stillness past the hold-off trips low-power rest, and any motion resets the timer.
- **`test_classifier.c`** , the confidence-gated cascade (`classifier.c`): the audio stage runs
  only when it is enabled, a model is present, audio exists for the cycle, and the IMU was unsure,
  and the more-confident stage wins. classifier.c's weak model hooks are overridden with scripted
  stubs.

Run (needs any host C compiler, e.g. gcc/clang):

```bash
make -C firmware/test check
```

## Continuous integration

`.github/workflows/test.yml` runs both the Python and the C suites on every push and pull request,
so the tests are exercised automatically even without a local C toolchain.

## Manual and on-hardware verification

The end-to-end behaviour that can't be unit-tested off-device was checked on the real hardware,
the collar (XIAO nRF52840 Sense) and the station (ESP32-S3), over USB serial, plus the
build and deploy steps. Each row was directly observed.

| # | Area | Condition / action | Expected | Result |
|---|------|--------------------|----------|--------|
| 1 | Model delivery | Boot the collar with OTA'd models in flash | Both slots load | Serial: `slot 0 loaded: 23616 bytes`, `slot 1 loaded: 19640 bytes` ✓ |
| 2 | On-device inference | Collar in production mode | Real class + confidence on a full window | Serial: `production: cls=… conf=…% (win=624/624)` ✓ |
| 3 | Activity gate → rest | Hold the collar still ~60 s | Drops to low-power rest | Serial: `activity: still >= 60s , entering low-power rest`, periodic logging stops ✓ |
| 4 | Wake on motion | Move the collar while resting | Wakes and resumes classification | Serial: `activity: motion , waking after Ns rest`, production resumes ✓ |
| 5 | Rest event | Collar rests, then wakes | Station logs the span as a `rest` episode | Station serial: `relay cat_… rest` for the dormant span (steps frozen) ✓ |
| 6 | REST mapping fix | Station running updated firmware | `0xFE` shown as `rest`, not `active` | Station relay reported `rest` after reflash (was `active` before) ✓ |
| 7 | Collar build | `west build` (NCS v3.3.1) | Builds, UF2 produced | FLASH 57.6 %, RAM 86.6 %, `zephyr.uf2` written ✓ |
| 8 | Station build | `idf.py build` (ESP-IDF) | Builds, image produced | `esp32_firebase_test.bin`, 22 % partition free ✓ |
| 9 | Docs build | `build.ps1` (XeLaTeX + Biber) | Compiles, no errors | PDF produced and published ✓ |
| 10 | Backend deploy | `firebase deploy` (rules + functions) | Released to `meowtion-app` | Rules released; `upload_clip`, `train`, `simulate(_now)` updated ✓ |

These complement the automated suites above: the unit tests pin the pure logic, and this table
records the integration behaviour confirmed on hardware.
