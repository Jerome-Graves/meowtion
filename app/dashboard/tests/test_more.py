"""More dashboard data-layer tests: Firebase-shape parsing, the time-window drill-down,
and the health-watch recent-vs-baseline comparison.

Run:  python -m pytest app/dashboard/tests
"""
import importlib.util
import pathlib

import pandas as pd

_DATA_PATH = pathlib.Path(__file__).resolve().parents[1] / "meowtion_dash" / "data.py"
_spec = importlib.util.spec_from_file_location("mw_data_more", _DATA_PATH)
mw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mw)


# ----- iter_cats / list_cats: parse both the station-nested and standalone shapes -----

def test_iter_cats_handles_station_nested_and_standalone():
    data = {"devices": {
        "sta": {"type": "station", "name": "Hub",
                "cats": {"cat_a": {"current": {"steps": 3}, "events": {}}}},
        "cat_a": {"name": "Whiskers"},                                  # registry entry (name)
        "cat_b": {"events": {"1": {"start": 1, "type": "eat", "durationSec": 1}}},  # standalone
    }}
    recs = {r["id"]: r for r in mw.iter_cats(data)}
    assert set(recs) == {"cat_a", "cat_b"}
    assert recs["cat_a"]["name"] == "Whiskers"   # resolved from the registry device
    assert recs["cat_a"]["via"] == "Hub"
    assert recs["cat_b"]["via"] is None          # standalone collar has no station


def test_list_cats_dedups_and_pairs_name_id():
    data = {"devices": {
        "sta": {"type": "station", "cats": {"cat_a": {"current": {}, "events": {}}}},
        "cat_a": {"name": "Whiskers"},
    }}
    assert mw.list_cats(data) == [("Whiskers", "cat_a")]


# ----- period_options / filter_to_window: the Day/Week/Month drill-down -----

def _df(dates):
    return pd.DataFrame({"event_date": dates,
                         "activity": ["Eat"] * len(dates),
                         "event_duration": [1.0] * len(dates)})


def test_period_options_day_newest_first_deduped():
    df = _df(["2026-06-27", "2026-06-28", "2026-06-28"])
    keys = [k for _, k in mw.period_options(df, "Day")]
    assert keys == ["2026-06-28", "2026-06-27"]


def test_filter_to_window_day_and_month():
    df = _df(["2026-06-27", "2026-06-28", "2026-06-28", "2026-07-01"])
    day = mw.filter_to_window(df, "Day", "2026-06-28")
    assert len(day) == 2 and set(day["event_date"]) == {"2026-06-28"}
    june = mw.filter_to_window(df, "Month", "2026-06")
    assert set(june["event_date"]) == {"2026-06-27", "2026-06-28"}


# ----- health_signals: recent average and recent-vs-baseline change -----

def test_health_signals_recent_average_without_baseline():
    # 3 days only -> no day is dropped, and there is no baseline window yet.
    df = pd.DataFrame({"event_date": ["2026-06-26", "2026-06-27", "2026-06-28"],
                       "activity": ["Eating"] * 3, "event_duration": [10.0, 20.0, 30.0]})
    eat = next(s for s in mw.health_signals(df) if s["activity"] == "Eating")
    assert eat["recent"] == 20.0          # mean(10, 20, 30)
    assert eat["baseline"] is None
    assert eat["change_pct"] is None


def test_fmt_time_format():
    s = mw.fmt_time(0)
    assert "·" in s and ":" in s


def test_filter_by_weekday():
    df = pd.DataFrame({"event_weekday_name": ["Monday", "Saturday", "Sunday"],
                       "event_duration": [1, 2, 3]})
    assert set(mw.filter_by_weekday(df, ["Saturday", "Sunday"])["event_weekday_name"]) == {"Saturday", "Sunday"}
    assert list(mw.filter_by_weekday(df, "Monday")["event_weekday_name"]) == ["Monday"]


def test_filter_by_date_range():
    df = pd.DataFrame({"event_date": ["2026-06-26", "2026-06-27", "2026-06-28"],
                       "event_duration": [1, 2, 3]})
    both = mw.filter_by_date_range(df, "2026-06-27", "2026-06-28")
    assert set(both["event_date"]) == {"2026-06-27", "2026-06-28"}
    assert set(mw.filter_by_date_range(df, start="2026-06-28")["event_date"]) == {"2026-06-28"}


def test_last_n_days_keeps_recent_calendar_days():
    df = pd.DataFrame({"event_date": ["2026-06-26", "2026-06-27", "2026-06-28"],
                       "event_duration": [1, 2, 3]})
    assert set(mw.last_n_days(df, n=2)["event_date"]) == {"2026-06-27", "2026-06-28"}


def test_health_signals_reports_drop_vs_baseline():
    # 5 days: the latest (still-accumulating) day is dropped, leaving [100, 8, 8, 8].
    # baseline = the day before the recent window (100), recent = last 3 (8,8,8) -> -92%.
    dates = ["2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28"]
    df = pd.DataFrame({"event_date": dates, "activity": ["Eating"] * 5,
                       "event_duration": [100.0, 8.0, 8.0, 8.0, 999.0]})
    eat = next(s for s in mw.health_signals(df) if s["activity"] == "Eating")
    assert eat["recent"] == 8.0
    assert eat["baseline"] == 100.0
    assert eat["change_pct"] == -92.0


# ----- remaining branches: model_labels, non-dict skips, Week/Month paths, empty-input guards -----

def test_model_labels():
    assert mw.model_labels({"models": {"labels": ["eat", "drink"]}}) == ["eat", "drink"]
    assert mw.model_labels({}) == []
    assert mw.model_labels(None) == []


def test_iter_cats_skips_non_dict_entries():
    data = {"devices": {
        "junk": "not-a-dict",                                   # non-dict device is skipped
        "sta": {"type": "station",
                "cats": {"bad": 123,                            # non-dict cat is skipped
                         "cat_a": {"current": {}, "events": {}}}},
    }}
    assert {r["id"] for r in mw.iter_cats(data)} == {"cat_a"}


def test_period_options_empty_week_and_month():
    assert mw.period_options(pd.DataFrame({"event_date": []}), "Day") == []
    df = _df(["2026-06-27", "2026-07-02"])
    wk = mw.period_options(df, "Week")
    assert wk and all(label.startswith("Week of") for label, _ in wk)
    mo = mw.period_options(df, "Month")
    assert [label for label, _ in mo] == ["July 2026", "June 2026"]


def test_filter_to_window_empty_and_week():
    assert mw.filter_to_window(pd.DataFrame({"event_date": []}), "Day", "x").empty
    df = _df(["2026-06-29", "2026-07-10"])
    wk = mw.filter_to_window(df, "Week", "2026-06-29")      # 7-day window from the start date
    assert set(wk["event_date"]) == {"2026-06-29"}


def test_over_time_empty_and_day():
    empty = mw.over_time(pd.DataFrame(columns=["event_date", "start_time", "activity", "event_duration"]), "Day")
    assert empty.empty
    df = pd.DataFrame({"event_date": ["2026-06-28"], "start_time": ["10:30"],
                       "activity": ["Eat"], "event_duration": [2.0]})
    day = mw.over_time(df, "Day")                            # hourly binning path
    assert day["event_duration"].sum() == 2.0


def test_last_n_days_and_health_signals_handle_empty():
    assert mw.last_n_days(pd.DataFrame({"event_date": []}), n=3).empty
    assert mw.health_signals(pd.DataFrame({"activity": [], "event_date": [], "event_duration": []})) == []


def test_daily_segments_rows_per_day_with_time_of_day():
    # Rest 22:00 for 4h crosses midnight -> 22:00-24:00 on day 1, 00:00-02:00 on day 2,
    # both mapped onto the shared reference date for the time-of-day x-axis.
    df = pd.DataFrame({"event_date": ["2026-06-28"], "start_time": ["22:00"],
                       "activity": ["Rest"], "event_duration": [240.0]})
    out = mw.daily_segments(df).set_index("day")
    ref = pd.Timestamp("2000-01-01")
    assert set(out.index) == {"2026-06-28", "2026-06-29"}
    assert out.loc["2026-06-28", "start"] == ref + pd.Timedelta(hours=22)
    assert out.loc["2026-06-28", "end"] == ref + pd.Timedelta(hours=24)
    assert out.loc["2026-06-29", "start"] == ref
    assert out.loc["2026-06-29", "end"] == ref + pd.Timedelta(hours=2)


def test_daily_segments_skips_zero_and_empty():
    z = pd.DataFrame({"event_date": ["2026-06-28"], "start_time": ["10:00"],
                      "activity": ["Eat"], "event_duration": [0.0]})
    assert mw.daily_segments(z).empty
    assert mw.daily_segments(z.iloc[0:0]).empty


def _seg(day, mins):
    ref = pd.Timestamp("2000-01-01")
    return {"day": day, "start": ref, "end": ref + pd.Timedelta(minutes=mins), "activity": "Rest"}


def test_trim_sparse_edge_days_drops_thin_first_and_last():
    frame = pd.DataFrame([_seg("2026-06-02", 10), _seg("2026-06-03", 600), _seg("2026-06-04", 10)])
    assert set(mw.trim_sparse_edge_days(frame)["day"]) == {"2026-06-03"}


def test_trim_sparse_edge_days_keeps_thin_interior_day():
    frame = pd.DataFrame([_seg("2026-06-02", 600), _seg("2026-06-03", 10), _seg("2026-06-04", 600)])
    assert set(mw.trim_sparse_edge_days(frame)["day"]) == {"2026-06-02", "2026-06-03", "2026-06-04"}


def test_trim_sparse_edge_days_handles_single_and_empty():
    assert len(mw.trim_sparse_edge_days(pd.DataFrame([_seg("2026-06-02", 5)]))) == 1
    assert mw.trim_sparse_edge_days(pd.DataFrame(columns=["day", "start", "end", "activity"])).empty
