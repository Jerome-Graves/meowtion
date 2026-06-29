"""Unit tests for the Cloud Function's input validation and WAV parsing.

The path-segment regexes are a security control (they keep attacker-controlled `collar`/`ts`
values from escaping the owner's Storage prefix), so they are worth pinning down. parse_wav is
the entry point that turns an uploaded clip into samples for training.

Run:  python -m pytest app/firebase/functions/tests
"""
import struct

import numpy as np
import pytest

import main   # importable because conftest.py stubs the Firebase SDKs


# ----- path-segment validation (anti path-traversal / injection) -----

@pytest.mark.parametrize("good", ["cat_64582d", "abc-123_XYZ", "A", "0"])
def test_safe_id_accepts_valid_segments(good):
    assert main._SAFE_ID.match(good)


@pytest.mark.parametrize("bad", ["../etc", "a/b", "a..b/", "a.b", "a b", "a;b", "", "a/../b", "..", "a\\b"])
def test_safe_id_rejects_traversal_and_separators(bad):
    assert not main._SAFE_ID.match(bad)


def test_safe_ts_accepts_digits_only():
    assert main._SAFE_TS.match("1719600000000")


@pytest.mark.parametrize("bad", ["12a", "-1", "1.0", "../1", "", "1 2", "0x10"])
def test_safe_ts_rejects_non_digits(bad):
    assert not main._SAFE_TS.match(bad)


# ----- WAV parsing -----

def _wav(samples, rate=8000):
    pcm = np.asarray(samples, dtype="<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)   # PCM mono 16-bit
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt +
              b"data" + struct.pack("<I", len(pcm)) + pcm)
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def test_parse_wav_roundtrips_samples():
    samples, rate = main.parse_wav(_wav([0, 1, -1, 32767, -32768], rate=8000))
    assert rate == 8000
    assert list(samples) == [0, 1, -1, 32767, -32768]


def test_parse_wav_reads_rate_from_fmt_chunk():
    _, rate = main.parse_wav(_wav([1, 2, 3], rate=16000))
    assert rate == 16000


def test_parse_wav_rejects_non_wav():
    with pytest.raises(ValueError):
        main.parse_wav(b"NOPEnope" + b"\x00" * 16)


def test_parse_wav_requires_a_data_chunk():
    fmt = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    buf = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks
    with pytest.raises(ValueError):
        main.parse_wav(buf)
