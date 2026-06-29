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
