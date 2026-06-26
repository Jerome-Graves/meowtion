"""Branded chart helpers, so the dashboard's charts share one look without repeating the
Altair styling each time.
"""
import altair as alt

ACCENT = "#bc7bc2"   # brand lavender


def bar(data, x, y, y_title):
    """A branded Altair bar chart: lavender bars on a transparent background (so it sits on
    the page's gradient, not in a white panel). `x`/`y` are column names.

    Example:
        counts = df["activity"].value_counts().reset_index()
        counts.columns = ["activity", "count"]
        st.altair_chart(mw.bar(counts, "activity", "count", "episodes"), use_container_width=True)
    """
    return (
        alt.Chart(data)
        .mark_bar(color=ACCENT, cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=34)
        .encode(
            x=alt.X(f"{x}:N", title=None, sort="-y",
                    axis=alt.Axis(labelAngle=0, labelColor="#3a3a4a", labelFontWeight=600)),
            y=alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(labelColor="#6b7280", titleColor="#6b7280")),
            tooltip=[x, y],
        )
        .properties(height=260, background="transparent")
        .configure_view(fill=None, stroke=None)
        .configure_axis(grid=False, domainColor="#e6e7ec", tickColor="#e6e7ec")
    )
