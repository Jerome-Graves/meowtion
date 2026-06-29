"""Branded chart helpers, so the dashboard's charts share one look without repeating the
Altair styling each time.
"""
import altair as alt

ACCENT = "#bc7bc2"   # brand lavender

# Colours are assigned to activities PROGRAMMATICALLY, by sorted position in a fixed palette, so the
# scheme is agnostic to whatever activity names the model produces. A given activity always gets the
# same colour, and the filter buttons and the charts share this one mapping (activity_colors) so they
# always match.
PALETTE = [
    "#4caf7d",  # green
    "#3d9bd6",  # blue
    "#e8943a",  # orange
    "#9b8bd6",  # purple
    "#c77bb0",  # pink
    "#e0b020",  # amber
    "#48bfae",  # teal
    "#e07a5f",  # coral
    "#6c5cc2",  # indigo
    "#5cba8a",  # mint
]


def activity_colors(activities):
    """Map each activity to a palette colour by its sorted position. Name-agnostic and stable, so
    a given activity gets the same colour regardless of which others are present. Returns
    {activity: hex}; share it between the filter buttons and the chart so they match."""
    ordered = sorted({str(a) for a in activities})
    return {a: PALETTE[i % len(PALETTE)] for i, a in enumerate(ordered)}


def activity_scale(activities=None, colors=None):
    """An Altair colour scale for activities. Pass a precomputed `colors` map (so a chart matches the
    buttons exactly) or an iterable of `activities` to derive one."""
    cmap = colors if colors is not None else activity_colors(activities or [])
    return alt.Scale(domain=list(cmap), range=list(cmap.values()))


def stacked_bar(data, x, y, color, y_title=None, time_unit=None, time_format="%d %b",
                legend=True, height=300, colors=None, x_domain=None):
    """A branded bar chart split by colour into the `color` column (e.g. activity), transparent
    background.

    For a date/time x, pass `time_unit` (e.g. "yearmonthdate" for days, "yearmonthdatehours" for
    hours): the bars are then binned to that unit, so each gets ONE fat band and ONE axis label,
    instead of thin bars and a repeated label at every tick. `time_format` styles those labels.
    """
    cats = sorted(map(str, data[color].unique()))
    if time_unit:
        # x_domain (e.g. midnight->midnight) forces the axis to cover the whole period rather than
        # only the hours/days that happen to have data.
        x_enc = alt.X(f"{x}:T", timeUnit=time_unit, title=None,
                      scale=alt.Scale(domain=x_domain, nice=False) if x_domain else alt.Undefined,
                      axis=alt.Axis(format=time_format, labelColor="#3a3a4a", labelFontWeight=600, labelAngle=0))
        y_enc = alt.Y(f"sum({y}):Q", title=y_title, axis=alt.Axis(labelColor="#6b7280", titleColor="#6b7280"))
    else:
        x_enc = alt.X(f"{x}:N", title=None, sort="-y",
                      axis=alt.Axis(labelAngle=0, labelColor="#3a3a4a", labelFontWeight=600))
        y_enc = alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(labelColor="#6b7280", titleColor="#6b7280"))
    leg = alt.Legend(title=None, orient="bottom", labelColor="#3a3a4a") if legend else None
    return (
        alt.Chart(data)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=x_enc,
            y=y_enc,
            color=alt.Color(f"{color}:N",
                            scale=(activity_scale(colors=colors) if colors else activity_scale(cats)),
                            legend=leg),
            tooltip=[color, y],
        )
        .properties(height=height, background="transparent")
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
