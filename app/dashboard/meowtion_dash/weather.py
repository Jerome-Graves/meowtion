"""Weather context for the analysis. The station already polls Open-Meteo and stores the readings
under each station's `weather/history`, so here we just read that history, summarise it per day,
and compare a window to the cat's overall normal , so a behaviour change can be read against
whether it was an unusually hot / cold / wet / snowy period.
"""
import datetime

import pandas as pd

_COND_EMOJI = {"clear": "☀️", "cloudy": "☁️", "rain": "🌧", "snow": "❄️",
               "thunder": "⛈", "fog": "🌫", "?": "🌤"}


def weather_dataframe(data):
    """Daily weather from the stations' stored history. One row per date:
        event_date | tempC (mean) | tmin | tmax | condition (most common) | rainy | snowy
    Empty if the station hasn't recorded any weather yet.
    """
    cols = ["event_date", "tempC", "tmin", "tmax", "condition", "rainy", "snowy"]
    rows = []
    for station in (data or {}).get("devices", {}).values():
        if not isinstance(station, dict):
            continue
        for ts, w in (((station.get("weather") or {}).get("history")) or {}).items():
            if not isinstance(w, dict):
                continue
            try:
                day = datetime.datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
            except (ValueError, TypeError, OverflowError):
                continue
            rows.append({"event_date": day, "tempC": w.get("tempC"),
                         "condition": w.get("condition", "?"), "raining": bool(w.get("raining"))})
    if not rows:
        return pd.DataFrame(columns=cols)
    raw = pd.DataFrame(rows)
    raw["tempC"] = pd.to_numeric(raw["tempC"], errors="coerce")
    out = []
    for day, g in raw.groupby("event_date"):
        conds = g["condition"]
        out.append({
            "event_date": day,
            "tempC": g["tempC"].mean(),
            "tmin": g["tempC"].min(),
            "tmax": g["tempC"].max(),
            "condition": conds.mode().iat[0] if not conds.mode().empty else "?",
            "rainy": bool(g["raining"].any()),
            "snowy": bool((conds == "snow").any()),
        })
    return pd.DataFrame(out, columns=cols)


def window_weather(wdf, dates):
    """Summarise weather for `dates`, compared to ALL stored weather (the cat's 'normal').
    Returns None if there's no weather for those dates, else a dict with the averages and an
    `unusual` list of plain-English flags (unusually warm/cold, wetter than usual, snow)."""
    if wdf is None or wdf.empty:
        return None
    win = wdf[wdf["event_date"].isin(set(map(str, dates)))]
    if win.empty or win["tempC"].notna().sum() == 0:
        return None

    avg, base_avg = win["tempC"].mean(), wdf["tempC"].mean()
    unusual = []
    if pd.notna(avg) and pd.notna(base_avg) and len(wdf) >= 5:   # need some baseline to compare
        diff = avg - base_avg
        if diff >= 3:
            unusual.append(f"unusually warm ({avg:.0f}°C vs ~{base_avg:.0f}°C normal)")
        elif diff <= -3:
            unusual.append(f"unusually cold ({avg:.0f}°C vs ~{base_avg:.0f}°C normal)")
    if pd.notna(wdf["rainy"].mean()) and win["rainy"].mean() - wdf["rainy"].mean() >= 0.25:
        unusual.append("wetter than usual")
    if win["snowy"].any():
        unusual.append("snow")

    return {"avg": avg, "tmin": win["tmin"].min(), "tmax": win["tmax"].max(),
            "rainy_days": int(win["rainy"].sum()), "snowy_days": int(win["snowy"].sum()),
            "condition": win["condition"].mode().iat[0] if not win["condition"].mode().empty else "?",
            "unusual": unusual}


def weather_caption(summary):
    """A one-line caption from a window_weather() dict, or None."""
    if not summary:
        return None
    parts = [f"{_COND_EMOJI.get(summary['condition'], '🌤')} avg {summary['avg']:.0f}°C "
             f"({summary['tmin']:.0f}–{summary['tmax']:.0f}°C)"]
    if summary["rainy_days"]:
        parts.append(f"{summary['rainy_days']} rainy day(s)")
    if summary["snowy_days"]:
        parts.append(f"{summary['snowy_days']} snowy day(s)")
    text = "  ·  ".join(parts)
    if summary["unusual"]:
        text += "  ·  ⚠ " + ", ".join(summary["unusual"])
    return text
