"""Turn the raw Firebase JSON into a clean, chart-ready pandas DataFrame, plus small
helpers for formatting and filtering. The dashboard view uses these; it never has to
understand the Firebase structure itself.
"""
import datetime

import pandas as pd

# Emoji per activity, for the live cards and any labelled chart. Unknown -> a neutral dot.
EVENT_ICON = {"resting": "🛋", "moving": "🐾", "sleep": "😴", "rest": "🛋", "active": "🐾",
              "walk": "🚶", "play": "🧶", "groom": "🧼", "drink": "💧", "eat": "🍽", "purr": "💜"}


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


def activity_dataframe(data, labels):
    """Flatten every cat's logged episodes into one DataFrame, one row per episode.

    Columns (chosen to match the beginner Streamlit tutorial, so tutorial chart code just works):

        cat | activity | event_date | event_weekday_name | start_time | event_duration

    `event_duration` is in minutes. `activity` is the trained model's label for real
    (ver == 2) episodes, otherwise the stored state name.
    """
    devices = (data or {}).get("devices", {})
    rows = []
    for station in devices.values():
        if not isinstance(station, dict):
            continue
        for cat_id, cat in (station.get("cats") or {}).items():
            cat_name = (devices.get(cat_id) or {}).get("name") or cat.get("name") or cat_id
            for ev in (cat.get("events") or {}).values():
                start = ev.get("start")
                if not isinstance(start, (int, float)):
                    continue
                dt = datetime.datetime.fromtimestamp(start / 1000)
                ecls = ev.get("cls")
                if ev.get("ver") == 2 and isinstance(ecls, int) and 0 <= ecls < len(labels):
                    activity = labels[ecls]                # real on-device class -> action name
                else:
                    activity = ev.get("type", "unknown")   # older / simulated episode
                rows.append({
                    "cat": cat_name,
                    "activity": str(activity).capitalize(),
                    "event_date": dt.strftime("%Y-%m-%d"),
                    "event_weekday_name": dt.strftime("%A"),
                    "start_time": dt.strftime("%H:%M"),
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
    """Sum `value` along the x-axis of the chosen window: per HOUR within a Day, per DATE within a
    Week or Month. Returns columns `when` (a datetime) and `value`, for a temporal bar chart."""
    if df.empty:
        return pd.DataFrame(columns=["when", value])
    if period == "Day":
        when = pd.to_datetime(df["event_date"] + " " + df["start_time"]).dt.floor("h")  # the hour
    else:
        when = pd.to_datetime(df["event_date"]).dt.normalize()                          # the date
    return df.assign(when=when).groupby("when")[value].sum().reset_index()
