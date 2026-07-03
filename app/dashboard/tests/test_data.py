"""Unit tests for the dashboard data layer (meowtion_dash/data.py).

These cover the pure transforms that turn raw Firebase JSON into the chart-ready
DataFrame, including the rules-based low-power-rest event handling (class byte
0xFE -> a "rest" episode rather than a model label).

Run:  python -m pytest app/dashboard/tests
"""
import importlib.util
import pathlib

import pandas as pd

# Load data.py directly so we don't trigger the package __init__ (which imports Streamlit).
_DATA_PATH = pathlib.Path(__file__).resolve().parents[1] / "meowtion_dash" / "data.py"
_spec = importlib.util.spec_from_file_location("mw_data", _DATA_PATH)
mw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mw)


def _data_with_events(events):
    """A minimal Firebase snapshot: one station with one cat carrying `events`."""
    return {"devices": {"tok": {"type": "station", "cats": {"cat_abc": {"events": events}}}}}


def test_fmt_dur_under_and_over_a_minute():
    assert mw.fmt_dur(45) == "45s"
    assert mw.fmt_dur(125) == "2m 05s"


def test_activity_dataframe_maps_class_index_to_label():
    data = _data_with_events({"1000": {"start": 1000, "durationSec": 120, "ver": 2, "cls": 0}})
    df = mw.activity_dataframe(data, ["eat", "drink"])
    assert list(df["activity"]) == ["Eating"]        # labels[0], canonical display name
    assert df["event_duration"].iloc[0] == 2.0       # 120 s -> 2 min


def test_activity_dataframe_rest_event_uses_type_not_class():
    # 0xFE (254) is the low-power-rest sentinel, not a valid label index, so the row
    # must fall back to the event "type" instead of indexing the label list.
    data = _data_with_events({"2000": {"start": 2000, "durationSec": 600, "ver": 2,
                                       "cls": 254, "type": "rest"}})
    df = mw.activity_dataframe(data, ["eat", "drink"])
    assert list(df["activity"]) == ["Resting"]
    assert df["event_duration"].iloc[0] == 10.0


def test_activity_dataframe_v1_event_uses_type():
    data = _data_with_events({"3000": {"start": 3000, "durationSec": 60, "type": "groom"}})
    df = mw.activity_dataframe(data, ["eat", "drink"])
    assert list(df["activity"]) == ["Grooming"]


def test_activity_dataframe_skips_malformed_events():
    data = _data_with_events({"bad": {"durationSec": 60, "type": "eat"}})   # no start
    df = mw.activity_dataframe(data, [])
    assert df.empty


def test_filter_by_activity_single_and_list():
    df = pd.DataFrame({"activity": ["Eat", "Drink", "Rest"], "event_duration": [1, 2, 3]})
    assert list(mw.filter_by_activity(df, "Eat")["activity"]) == ["Eat"]
    assert set(mw.filter_by_activity(df, ["Eat", "Rest"])["activity"]) == {"Eat", "Rest"}


def test_over_time_sums_duration_by_activity():
    df = mw.activity_dataframe(_data_with_events({
        "1000": {"start": 1000, "durationSec": 120, "ver": 2, "cls": 0},
        "2000": {"start": 2000, "durationSec": 60, "ver": 2, "cls": 0},
    }), ["eat"])
    out = mw.over_time(df, "Week")                    # same day -> summed
    assert out["event_duration"].sum() == 3.0         # (120 + 60) / 60
