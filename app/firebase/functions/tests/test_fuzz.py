"""Property/fuzz tests for the Cloud Function's untrusted-input surface.

These hunt for crashes and validation bypasses the way an adversary would: they encode the INVARIANT
each control is supposed to hold, then throw both hand-picked adversarial inputs and thousands of
seeded-random inputs at it and check the invariant never breaks. No external fuzzing engine , stdlib
`random` only , so this runs in CI with the existing pytest.

Two surfaces matter most:
  * the path-segment validators (`_SAFE_ID` / `_SAFE_TS`): a value they accept is interpolated into a
    Storage object path, so anything they let through is attacker-controlled path content;
  * `parse_wav`: it turns fully attacker-controlled uploaded bytes into samples, so it must fail
    cleanly (ValueError) on garbage, never with an unexpected exception.

Run:  python -m pytest app/firebase/functions/tests/test_fuzz.py
"""
import random
import struct

import numpy as np
import pytest

import main   # importable because conftest.py stubs the Firebase SDKs

ALLOWED_ID = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
ALLOWED_TS = set("0123456789")

# Characters an attacker would try to smuggle past the validators: line terminators (the classic
# Python `$` / re.match trailing-newline bypass), NUL, path separators, traversal, and spacing.
TRICKY = list("\n\r\x00\t\x0b\x0c./\\ ;:%")


# --------------------------------------------------------------------------- #
# Path-segment validators , invariant: MATCH implies the string is only allowed characters.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", ["abc\n", "a\n", "9\n", "cat_1\r", "cat_1\x00", "\n", "abc\n\n"])
def test_safe_id_rejects_trailing_terminators_and_nul(bad):
    # A trailing newline/CR/NUL must NOT be accepted: it would ride into training/<owner>/<collar>/...
    assert not main._SAFE_ID.match(bad), f"_SAFE_ID accepted {bad!r}"


@pytest.mark.parametrize("bad", ["123\n", "1\r", "0\x00", "42\n"])
def test_safe_ts_rejects_trailing_terminators_and_nul(bad):
    assert not main._SAFE_TS.match(bad), f"_SAFE_TS accepted {bad!r}"


def test_safe_id_match_implies_only_allowed_charset_fuzz():
    rng = random.Random(0xC0FFEE)
    pool = list(ALLOWED_ID) + TRICKY
    offenders = []
    for _ in range(40000):
        s = "".join(rng.choice(pool) for _ in range(rng.randint(1, 10)))
        if main._SAFE_ID.match(s) and any(ch not in ALLOWED_ID for ch in s):
            offenders.append(s)
    assert not offenders, f"_SAFE_ID accepted unsafe strings, e.g. {sorted(set(offenders))[:5]!r}"


def test_safe_ts_match_implies_only_digits_fuzz():
    rng = random.Random(0xBADF00D)
    pool = list(ALLOWED_TS) + TRICKY + list("abcdef-")
    offenders = []
    for _ in range(40000):
        s = "".join(rng.choice(pool) for _ in range(rng.randint(1, 10)))
        if main._SAFE_TS.match(s) and any(ch not in ALLOWED_TS for ch in s):
            offenders.append(s)
    assert not offenders, f"_SAFE_TS accepted non-digit strings, e.g. {sorted(set(offenders))[:5]!r}"


# --------------------------------------------------------------------------- #
# parse_wav , invariant: on ANY bytes, either return (int16 ndarray, int) or raise ValueError.
# Never a different exception (struct.error, IndexError, ...), never hang.
# --------------------------------------------------------------------------- #
def _assert_parse_wav_contract(buf):
    try:
        out = main.parse_wav(buf)
    except ValueError:
        return                                   # the documented failure mode , fine
    except Exception as ex:                      # noqa: BLE001 , that's the point of the test
        pytest.fail(f"parse_wav raised {type(ex).__name__} on {buf!r}: {ex}")
    samples, rate = out
    assert samples.dtype == np.dtype("<i2"), "samples must be little-endian int16"
    assert isinstance(rate, int)


def test_parse_wav_truncated_fmt_chunk_fails_cleanly():
    # A "fmt " chunk header that declares a body the buffer doesn't contain: reading the sample rate
    # walks off the end. Must surface as ValueError, not a raw struct.error.
    buf = b"RIFF" + struct.pack("<I", 0) + b"WAVE" + b"fmt " + struct.pack("<I", 16)
    _assert_parse_wav_contract(buf)


def test_parse_wav_fuzz_random_bytes():
    rng = random.Random(0x5EED)
    for _ in range(6000):
        n = rng.randint(0, 96)
        buf = bytes(rng.getrandbits(8) for _ in range(n))
        # Half the time, prepend a valid RIFF/WAVE header so the fuzzer reaches the chunk loop where
        # the interesting parsing (and the interesting bugs) live, instead of bouncing off line 1.
        if rng.random() < 0.5:
            buf = b"RIFF" + bytes(rng.getrandbits(8) for _ in range(4)) + b"WAVE" + buf
        _assert_parse_wav_contract(buf)


def test_parse_wav_fuzz_structured_chunks():
    # Build syntactically-plausible chunk streams with adversarial sizes, so we exercise the size
    # arithmetic (huge sizes, odd sizes, zero sizes) rather than mostly-garbage bytes.
    rng = random.Random(0x1234)
    for _ in range(6000):
        body = b""
        for _ in range(rng.randint(0, 4)):
            cid = rng.choice([b"fmt ", b"data", b"LIST", b"junk", bytes(rng.getrandbits(8) for _ in range(4))])
            sz = rng.choice([0, 1, 2, 3, 8, 16, rng.randint(0, 1 << 31)])
            payload = bytes(rng.getrandbits(8) for _ in range(min(sz, rng.randint(0, 40))))
            body += cid + struct.pack("<I", sz) + payload
        buf = b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body
        _assert_parse_wav_contract(buf)


# --------------------------------------------------------------------------- #
# DSP helpers , robustness confirmation (these are expected to hold; the fuzz is the evidence).
# --------------------------------------------------------------------------- #
def test_per_window_norm_is_finite_and_bounded_fuzz():
    rng = random.Random(0xA11CE)
    for _ in range(3000):
        rows, cols = rng.randint(1, 60), rng.randint(1, main.IMU_AXES)
        x = np.array([[rng.randint(-32768, 32767) for _ in range(cols)] for _ in range(rows)],
                     dtype=np.int16)
        out = main.per_window_norm(x)
        assert np.all(np.isfinite(out)), f"per_window_norm produced NaN/inf for shape {x.shape}"
        assert np.max(np.abs(out)) <= 1.0 + 1e-3, "per_window_norm output not bounded to ~[-1, 1]"


def test_windows_always_yield_exact_window_length_fuzz():
    rng = random.Random(0xF00D)
    for _ in range(3000):
        n, win, hop = rng.randint(0, 400), rng.randint(1, 200), rng.randint(1, 200)
        arr = np.zeros((n, 1), dtype=np.int16)
        for w in main.windows(arr, win, hop):
            assert w.shape[0] == win, f"windows yielded length {w.shape[0]} != win {win} (n={n}, hop={hop})"
