"""Branded chart helpers, so the dashboard's charts share one look without repeating the
Altair styling each time.
"""
import altair as alt

ACCENT = "#bc7bc2"   # brand lavender


def bar(data, x, y, y_title=None, temporal=False, time_format="%d %b"):
    """A branded Altair bar chart: lavender bars on a TRANSPARENT background, so it sits on the
    page's gradient instead of in a clashing white panel. `x`/`y` are column names.

    Pass temporal=True when `x` is a date/time column: bars stay in chronological order with dated
    axis labels. `time_format` controls those labels, e.g. "%d %b" for dates or "%H:%M" for hours.

    Examples:
        counts = df["activity"].value_counts().reset_index()
        counts.columns = ["activity", "count"]
        st.altair_chart(mw.bar(counts, "activity", "count", "episodes"), use_container_width=True)

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
