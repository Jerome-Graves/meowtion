"""Turn the raw Firebase JSON into a clean, chart-ready pandas DataFrame, plus small
helpers for formatting and filtering. The dashboard view uses these; it never has to
understand the Firebase structure itself.
"""
import datetime

import pandas as pd

# Emoji per activity, for the live cards and any labelled chart. Unknown -> a neutral dot.
EVENT_ICON = {"resting": "🛋", "moving": "🐾", "eating": "🍽", "drinking": "💧",
              "purring": "💜", "grooming": "🧼",
              "sleep": "😴", "rest": "🛋", "active": "🐾", "walk": "🚶", "play": "🧶",
              "groom": "🧼", "drink": "💧", "eat": "🍽", "purr": "💜"}


def fmt_time(ms):
    """Epoch milliseconds -> 'dd Mon · HH:MM'."""
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%d %b · %H:%M")


def fmt_dur(s):
    """Seconds -> '2m 05s' (or '45s' under a minute)."""
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def model_labels(data):
    """The trained model's class names. The collar reports a class INDEX in its telemetry;
    we map index -> name here, so the collar stays label-agnostic."""
    return (data or {}).get("models", {}).get("labels") or []


def iter_cats(data):
    """Yield one record per cat/collar, whether it's nested under a station or STANDALONE (a
    simulated collar needs no station , its data sits directly on the device). Each record:
        {id, name, events, current, simulated, weather, via, path}
    `path` is the cat node under users/<uid>/ (used by fetch_live to read just the live bits)."""
    devices = (data or {}).get("devices", {})
    for dev_id, dev in devices.items():
        if not isinstance(dev, dict):
            continue
        if dev.get("type") == "station":
            wx = (dev.get("weather") or {}).get("current")
            for cat_id, cat in (dev.get("cats") or {}).items():
                if not isinstance(cat, dict):
                    continue
                reg = devices.get(cat_id) or {}
                yield {"id": cat_id,
                       "name": reg.get("name") or cat.get("name") or cat_id,
                       "events": cat.get("events") or {},
                       "current": cat.get("current") or {},
                       "simulated": bool(reg.get("simulated") or cat.get("simulated")),
                       "weather": wx, "via": dev.get("name", "station"),
                       "path": f"devices/{dev_id}/cats/{cat_id}"}
        elif dev.get("events") or dev.get("current"):     # standalone collar holding its own data
            yield {"id": dev_id,
                   "name": dev.get("name") or dev_id,
                   "events": dev.get("events") or {},
                   "current": dev.get("current") or {},
                   "simulated": bool(dev.get("simulated")),
                   "weather": (dev.get("weather") or {}).get("current"), "via": None,
                   "path": f"devices/{dev_id}"}


def list_cats(data):
    """Every cat/collar on the account as [(name, cat_id), ...]. For the collar switcher."""
    out, seen = [], set()
    for rec in iter_cats(data):
        if rec["id"] not in seen:
            seen.add(rec["id"])
            out.append((rec["name"], rec["id"]))
    return out


def activity_dataframe(data, labels):
    """Flatten every cat's logged events into one DataFrame, one row per event.

    Columns (chosen to match the beginner Streamlit tutorial, so tutorial chart code just works):

        cat | activity | event_date | event_weekday_name | start_time | event_duration

    `event_duration` is in minutes. `activity` is the trained model's label for real
    (ver == 2) events, otherwise the stored state name.
    """
    rows = []
    for rec in iter_cats(data):
        for ev in rec["events"].values():
            start = ev.get("start")
            if not isinstance(start, (int, float)):
                continue
            when = datetime.datetime.fromtimestamp(start / 1000)
            ecls = ev.get("cls")
            if ev.get("ver") == 2 and isinstance(ecls, int) and 0 <= ecls < len(labels):
                activity = labels[ecls]                # real on-device class -> action name
            else:
                activity = ev.get("type", "unknown")   # older / simulated event
            rows.append({
                "cat": rec["name"],
                "activity": str(activity).capitalize(),
                "event_date": when.strftime("%Y-%m-%d"),
                "event_weekday_name": when.strftime("%A"),
                "start_time": when.strftime("%H:%M"),
                "event_duration": round((ev.get("durationSec") or 0) / 60.0, 2),  # minutes
            })
    return pd.DataFrame(rows, columns=["cat", "activity", "event_date",
                                       "event_weekday_name", "start_time", "event_duration"])


# ---------------------------------------------------------------------------
# Filter helpers for the dashboard. Each takes the DataFrame and returns a new,
# filtered DataFrame, so they chain: filter_by_weekday(filter_by_activity(df, "Eat"), "Monday").
# ---------------------------------------------------------------------------
def filter_by_activity(df, activities):
    """Keep rows whose activity is `activities` (a single name or a list of names)."""
    if isinstance(activities, str):
        activities = [activities]
    return df[df["activity"].isin(activities)]


def filter_by_weekday(df, weekdays):
    """Keep rows on the given weekday name(s), e.g. 'Saturday' or ['Saturday', 'Sunday']."""
    if isinstance(weekdays, str):
        weekdays = [weekdays]
    return df[df["event_weekday_name"].isin(weekdays)]


def filter_by_date_range(df, start=None, end=None):
    """Keep rows with event_date (YYYY-MM-DD) between `start` and `end`, inclusive.
    Either bound may be None. Dates are ISO strings, so a plain string compare is correct."""
    out = df
    if start:
        out = out[out["event_date"] >= str(start)]
    if end:
        out = out[out["event_date"] <= str(end)]
    return out


def last_n_days(df, n=7):
    """Keep rows from the most recent `n` calendar days present in the data."""
    if df.empty:
        return df
    latest = datetime.date.fromisoformat(df["event_date"].max())
    cutoff = (latest - datetime.timedelta(days=n - 1)).isoformat()
    return df[df["event_date"] >= cutoff]


# ---------------------------------------------------------------------------
# Drill-down by time window. The dashboard lets the viewer pick a span (one Day,
# Week, or Month) and which specific window, then charts just that window.
# ---------------------------------------------------------------------------
def period_options(df, period):
    """The distinct Day / Week / Month windows present in df, newest first.

    Returns a list of (label, key) pairs; `key` is what filter_to_window() expects.
    """
    if df.empty:
        return []
    dates = pd.to_datetime(df["event_date"])
    if period == "Week":
        starts = sorted(set(dates.dt.to_period("W").dt.start_time), reverse=True)
        return [(f"Week of {d.strftime('%d %b %Y')}", d.strftime("%Y-%m-%d")) for d in starts]
    if period == "Month":
        months = sorted(set(dates.dt.to_period("M").astype(str)), reverse=True)   # "YYYY-MM"
        return [(pd.Period(m).strftime("%B %Y"), m) for m in months]
    days = sorted(set(df["event_date"]), reverse=True)                            # "YYYY-MM-DD"
    return [(pd.to_datetime(d).strftime("%a %d %b %Y"), d) for d in days]


def filter_to_window(df, period, key):
    """Keep only the rows inside the chosen window (the `key` from period_options)."""
    if df.empty or not key:
        return df.iloc[0:0]
    if period == "Week":
        start = pd.to_datetime(key)
        dates = pd.to_datetime(df["event_date"])
        return df[(dates >= start) & (dates < start + pd.Timedelta(days=7))]
    if period == "Month":
        return df[df["event_date"].str.startswith(key)]   # key is "YYYY-MM"
    return df[df["event_date"] == key]                    # key is one day


def over_time(df, period, value="event_duration"):
    """Sum `value` along the x-axis of the chosen window, SPLIT BY ACTIVITY: per HOUR within a Day,
    per DATE within a Week or Month. Returns columns `when` (datetime), `activity`, and `value`,
    ready for a stacked bar chart coloured by activity."""
    if df.empty:
        return pd.DataFrame(columns=["when", "activity", value])
    if period == "Day":
        when = pd.to_datetime(df["event_date"] + " " + df["start_time"]).dt.floor("h")  # the hour
    else:
        when = pd.to_datetime(df["event_date"]).dt.normalize()                          # the date
    return df.assign(when=when).groupby(["when", "activity"])[value].sum().reset_index()


def hourly_segments(df):
    """Break each event into per-hour segments at their real minute offsets, so a chart can show
    WHEN activity happened (a coloured block from start_min to end_min within each hour) instead of
    an aggregated total. An event at 10:50 lasting 30 min yields (10:00, 50, 60) and (11:00, 0, 20).
    Returns columns `when` (the hour), `activity`, `start_min` and `end_min` (minute-of-hour, 0..60).
    """
    cols = ["when", "activity", "start_min", "end_min"]
    rows = []
    for _, e in df.iterrows():
        start = pd.to_datetime(f"{e['event_date']} {e['start_time']}")
        end = start + pd.Timedelta(minutes=float(e["event_duration"]))
        if end <= start:                                       # zero/negative duration: nothing to draw
            continue
        bucket = start.floor("h")
        while bucket < end:
            nxt = bucket + pd.Timedelta(hours=1)
            seg_start, seg_end = max(start, bucket), min(end, nxt)
            rows.append({"when": bucket, "activity": e["activity"],
                         "start_min": (seg_start - bucket).total_seconds() / 60.0,
                         "end_min": (seg_end - bucket).total_seconds() / 60.0})
            bucket = nxt
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols)


def event_spans(df):
    """One row per event with absolute start/end timestamps, for a Gantt-style timeline across a
    multi-day range. Columns: `start`, `end` (timestamps), `activity`."""
    cols = ["start", "end", "activity"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    start = pd.to_datetime(df["event_date"].astype(str) + " " + df["start_time"].astype(str))
    end = start + pd.to_timedelta(df["event_duration"].astype(float), unit="m")
    return pd.DataFrame({"start": start.to_numpy(), "end": end.to_numpy(),
                         "activity": df["activity"].to_numpy()})


# Health-relevant habits, most informative first. Appetite and thirst changes are classic early
# warnings, and how much a cat grooms is one of the clearest behavioural health signals (grooming
# less can mean pain/illness; a lot more can mean stress or skin trouble), so those three lead, then
# rest (lethargy) and movement. Both the simulated labels (Eating/Drinking/Grooming/Purring) and any
# real-collar model labels (Eat/Drink/...) are listed so whichever a collar uses gets prioritised.
_HEALTH_PRIORITY = ["Eating", "Eat", "Drinking", "Drink", "Grooming", "Resting",
                    "Moving", "Purring", "Active", "Walk", "Sleep", "Play"]


def health_signals(df, recent_days=3, baseline_days=14, limit=4):
    """Compare each watched habit's RECENT daily average to a longer BASELINE, to surface routine
    changes worth noticing.

    Returns a list (most informative first) of dicts:
        {activity, recent, baseline, change_pct}   minutes/day; change_pct is None if no baseline.
    """
    if df.empty:
        return []
    present = set(df["activity"])
    watch = [a for a in _HEALTH_PRIORITY if a in present][:limit]
    daily = df.groupby(["event_date", "activity"])["event_duration"].sum().reset_index()
    all_days = sorted(df["event_date"].unique())   # days with any data; missing activity = 0 mins
    # Events are logged when an action ENDS, so the latest day is usually still in progress and
    # under-counts (e.g. a long overnight rest hasn't been written yet). Drop it so "recent vs usual"
    # compares whole days only, instead of reading a partial day as a sudden drop.
    if len(all_days) > recent_days + 1:
        all_days = all_days[:-1]
    out = []
    for act in watch:
        sub = daily[daily["activity"] == act]
        by_date = dict(zip(sub["event_date"], sub["event_duration"]))
        series = [by_date.get(d, 0.0) for d in all_days]
        recent = series[-recent_days:]
        base = series[max(0, len(series) - recent_days - baseline_days):len(series) - recent_days]
        r = sum(recent) / len(recent) if recent else 0.0
        b = (sum(base) / len(base)) if base else None
        change = ((r - b) / b * 100) if b else None
        out.append({"activity": act, "recent": r, "baseline": b, "change_pct": change})
    return out
