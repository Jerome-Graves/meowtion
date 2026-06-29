"""meowtion_dash , the dashboard's plumbing, behind one clean import.

app.py and dashboard_view.py import everything they need from here, so they never touch
cookies, JWTs, or the raw Firebase JSON.

    import meowtion_dash as mw

Wiring (used by app.py):
    mw.configure_page()                      set page config (call FIRST)
    mw.brand_header()                        render the brand bar
    mw.require_session() -> (uid, token, is_demo)
    mw.live_view(uid, token)                 live current-state cards
    mw.fetch(uid, token) -> (status, data)   cached Firebase read
    mw.activity_dataframe(data, labels)      -> clean DataFrame
    mw.model_labels(data)                    -> list[str]

For charts (used by dashboard_view.py):
    mw.filter_by_activity(df, names)
    mw.filter_by_weekday(df, days)
    mw.filter_by_date_range(df, start, end)
    mw.last_n_days(df, n)
    mw.bar(frame, x, y, y_title)             branded Altair bar chart
    mw.EVENT_ICON, mw.fmt_time, mw.fmt_dur
"""
from .theme import configure_page, brand_header
from .auth import require_session
from .firebase import fetch
from .data import (
    activity_dataframe, model_labels, list_cats, iter_cats, EVENT_ICON, fmt_time, fmt_dur,
    filter_by_activity, filter_by_weekday, filter_by_date_range, last_n_days,
    period_options, filter_to_window, over_time, hourly_segments, health_signals,
)
from .charts import bar, stacked_bar, intraday_timeline, activity_colors
from .weather import weather_dataframe, window_weather, weather_caption
from .live import live_view

__all__ = [
    "configure_page", "brand_header", "require_session", "fetch", "live_view",
    "activity_dataframe", "model_labels", "list_cats", "iter_cats", "EVENT_ICON", "fmt_time", "fmt_dur",
    "filter_by_activity", "filter_by_weekday", "filter_by_date_range", "last_n_days",
    "period_options", "filter_to_window", "over_time", "hourly_segments", "health_signals",
    "bar", "stacked_bar", "intraday_timeline", "activity_colors",
    "weather_dataframe", "window_weather", "weather_caption",
]
