"""Branded chart helpers, so the dashboard's charts share one look without repeating the
Altair styling each time.
"""
import altair as alt

ACCENT = "#bc7bc2"   # brand lavender

# Stable, intuitive colour per activity (warm = intake, cool = rest, green = movement), so a
# given activity is always the same colour across every chart. Unknown labels cycle a fallback.
ACTIVITY_COLORS = {
    "Eat": "#e8943a", "Drink": "#3d9bd6", "Resting": "#9b8bd6", "Moving": "#4caf7d",
    "Active": "#2bb3a3", "Walk": "#5cba8a", "Play": "#e0b020", "Sleep": "#6c5cc2",
    "Groom": "#c77bb0", "Purr": "#bc7bc2",
}
_FALLBACK = ["#e07a5f", "#3d9bd6", "#5cba8a", "#e0a32f", "#9b8bd6", "#c77bb0", "#6c757d", "#48bfae"]


def activity_scale(activities):
    """An Altair colour scale that maps each activity name to its fixed colour."""
    dom, rng, i = [], [], 0
    for a in activities:
        dom.append(a)
        if a in ACTIVITY_COLORS:
            rng.append(ACTIVITY_COLORS[a])
        else:
            rng.append(_FALLBACK[i % len(_FALLBACK)]); i += 1
    return alt.Scale(domain=dom, range=rng)


def stacked_bar(data, x, y, color, y_title=None, temporal=False, time_format="%d %b", legend=True):
    """A branded bar chart split by colour into the `color` column (e.g. activity), transparent
    background. Set temporal=True when `x` is a date/time column."""
    if temporal:
        x_enc = alt.X(f"{x}:T", title=None,
                      axis=alt.Axis(format=time_format, labelColor="#3a3a4a", labelFontWeight=600))
    else:
        x_enc = alt.X(f"{x}:N", title=None, sort="-y",
                      axis=alt.Axis(labelAngle=0, labelColor="#3a3a4a", labelFontWeight=600))
    leg = alt.Legend(title=None, orient="bottom", labelColor="#3a3a4a") if legend else None
    cats = sorted(map(str, data[color].unique()))
    return (
        alt.Chart(data)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=x_enc,
            y=alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(labelColor="#6b7280", titleColor="#6b7280")),
            color=alt.Color(f"{color}:N", scale=activity_scale(cats), legend=leg),
            tooltip=[color, y],
        )
        .properties(height=280, background="transparent")
        .configure_view(fill=None, stroke=None)
        .configure_axis(grid=False, domainColor="#e6e7ec", tickColor="#e6e7ec")
    )


def bar(data, x, y, y_title=None, temporal=False, time_format="%d %b"):
    """A branded Altair bar chart: lavender bars on a TRANSPARENT background, so it sits on the
    page's gradient instead of in a clashing white panel. `x`/`y` are column names.

    Pass temporal=True when `x` is a date/time column: bars stay in chronological order with dated
    axis labels. `time_format` controls those labels, e.g. "%d %b" for dates or "%H:%M" for hours.

    Examples:
        counts = df["activity"].value_counts().reset_index()
        counts.columns = ["activity", "count"]
        st.altair_chart(mw.bar(counts, "activity", "count", "events"), use_container_width=True)

        frame = mw.over_time(window, "Week")        # columns: when, event_duration
        st.altair_chart(mw.bar(frame, "when", "event_duration", "minutes", temporal=True),
                        use_container_width=True)
    """
    if temporal:
        x_enc = alt.X(f"{x}:T", title=None,
                      axis=alt.Axis(format=time_format, labelColor="#3a3a4a", labelFontWeight=600))
        mark = dict(color=ACCENT, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
    else:
        x_enc = alt.X(f"{x}:N", title=None, sort="-y",
                      axis=alt.Axis(labelAngle=0, labelColor="#3a3a4a", labelFontWeight=600))
        mark = dict(color=ACCENT, cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=34)
    return (
        alt.Chart(data)
        .mark_bar(**mark)
        .encode(
            x=x_enc,
            y=alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(labelColor="#6b7280", titleColor="#6b7280")),
            tooltip=[x, y],
        )
        .properties(height=260, background="transparent")
        .configure_view(fill=None, stroke=None)
        .configure_axis(grid=False, domainColor="#e6e7ec", tickColor="#e6e7ec")
    )
