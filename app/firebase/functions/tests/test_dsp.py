"""Unit tests for the Cloud Function's signal helpers (per_window_norm, windows).

These define the exact representation the model is trained on, and the collar must
reproduce the same maths at inference, so getting them right is a core correctness
property of the whole cascade. The Firebase SDKs are stubbed in conftest.py.

Run:  python -m pytest app/firebase/functions/tests
"""
import numpy as np

import main   # importable because conftest.py stubs the Firebase SDKs


def test_per_window_norm_is_zero_mean_and_bounded():
    x = np.array([[1.0], [2.0], [3.0]], dtype=np.float32)
    out = main.per_window_norm(x)
    assert abs(out.mean()) < 1e-5                 # per-channel mean removed
    assert out.max() <= 1.0 + 1e-6
    assert out.min() >= -1.0 - 1e-6              # scaled by global max-abs


def test_per_window_norm_matches_formula():
    x = np.array([[0.0], [10.0]], dtype=np.float32)
    out = main.per_window_norm(x)                 # mean 5 -> [-5, 5]; maxabs 5 -> [-1, 1]
    assert np.allclose(out.ravel(), [-1.0, 1.0], atol=1e-4)


def test_per_window_norm_normalises_each_channel_independently():
    x = np.array([[0.0, 100.0], [4.0, 104.0]], dtype=np.float32)
    out = main.per_window_norm(x)                 # both channels centre to +/-2 before scaling
    assert abs(out[:, 0].mean()) < 1e-5
    assert abs(out[:, 1].mean()) < 1e-5


def test_windows_pads_short_input_to_a_single_window():
    arr = np.ones((3, 2), dtype=np.float32)
    got = list(main.windows(arr, win=5, hop=2))
    assert len(got) == 1
    assert got[0].shape == (5, 2)
    assert (got[0][3:] == 0).all()               # zero-padded tail


def test_windows_slides_with_hop():
    arr = np.arange(10, dtype=np.float32).reshape(10, 1)
    got = list(main.windows(arr, win=4, hop=3))  # starts at 0, 3, 6
    assert len(got) == 3
    assert [int(w[0, 0]) for w in got] == [0, 3, 6]
    assert all(w.shape == (4, 1) for w in got)
