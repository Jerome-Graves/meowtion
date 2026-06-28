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

## Firmware (collar / station, C)

The on-device cascade logic (the rules-based activity gate in `activity.c` and the
confidence-gated cascade in `classifier.c`) is pure C and host-compilable, but running unit
tests for it needs a host C toolchain, which isn't part of the embedded build environment.
A host test harness under `firmware/test/` is planned; until then this logic is validated by
the on-hardware checks recorded in the project report.
