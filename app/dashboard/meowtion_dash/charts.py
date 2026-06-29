"""Branded chart helpers, so the dashboard's charts share one look without repeating the
Altair styling each time.
"""
import altair as alt
import pandas as pd

ACCENT = "#bc7bc2"   # brand lavender

# Colours are assigned to activities PROGRAMMATICALLY, by sorted position in a fixed palette, so the
# scheme is agnostic to whatever activity names the model produces. A given activity always gets the
# same colour, and the filter buttons and the charts share this one mapping (activity_colors) so they
# always match.
#
# Palette: colourblind-safe categorical colours (Okabe-Ito, plus two from Paul Tol to extend to 10),
# ordered so the first few activities get the most distinct hues. The reddish-purple sits with the
# lavender brand accent. Button labels pick black/white automatically (see readable_text) so they
# stay legible on the lighter colours too.
PALETTE = [
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#009E73",  # bluish green
    "#CC79A7",  # reddish purple (pairs with the lavender brand)
    "#56B4E9",  # sky blue
    "#D55E00",  # vermillion
    "#F0E442",  # yellow
    "#999999",  # grey
    "#332288",  # indigo (Tol)
    "#661100",  # dark red-brown (Tol)
]


def readable_text(hex_colour):
    """Return black or white, whichever reads better on `hex_colour` (by sRGB relative luminance).
    Used so an activity button's label stays legible whatever palette colour sits behind it."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#000000" if lum > 0.6 else "#FFFFFF"


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


def intraday_timeline(data, colors=None, x_domain=None, height=300):
    """A single-day timeline. Each row is a per-hour event segment (columns `when`, `activity`,
    `start_min`, `end_min`); it is drawn as a coloured block at its real minute offset within the
    hour (y from start_min to end_min, 0..60), so you can read WHEN activities happened across the
    day rather than just totals. Pass `colors` to match the filter buttons and `x_domain` (e.g.
    midnight->midnight) to span the whole day."""
    scale = activity_scale(colors=colors) if colors else activity_scale(sorted(map(str, data["activity"].unique())))
    return (
        alt.Chart(data)
        .mark_bar(cornerRadius=2)
        .encode(
            x=alt.X("when:T", timeUnit="yearmonthdatehours", title=None,
                    scale=alt.Scale(domain=x_domain, nice=False) if x_domain else alt.Undefined,
                    axis=alt.Axis(format="%H:%M", labelColor="#3a3a4a", labelFontWeight=600, labelAngle=0)),
            y=alt.Y("start_min:Q", title="minute of hour", scale=alt.Scale(domain=[0, 60]),
                    axis=alt.Axis(values=[0, 15, 30, 45, 60], labelColor="#6b7280", titleColor="#6b7280")),
            y2="end_min:Q",
            color=alt.Color("activity:N", scale=scale, legend=None),
            tooltip=["activity"],
        )
        .properties(height=height, background="transparent")
        .configure_view(fill=None, stroke=None)
        .configure_axis(grid=False, domainColor="#e6e7ec", tickColor="#e6e7ec")
    )


def event_timeline(data, colors=None, height=300, zoom_key=0):
    """Multi-day timeline drawn as rows of days: the y-axis is the calendar day and the x-axis is the
    time of day (spanning the data's actual range, shared across days). Each event is a horizontal bar from its start to
    its end time of day in its day's row, coloured by activity. `data` columns: `day`, `start`, `end`
    (time of day) and `activity` (see data.daily_segments). Pass `colors` to match the buttons.

    Scroll/drag zooms the time axis. `zoom_key` names the zoom selection: bump it (from a reset
    button) to change the spec, which remounts the chart at the full view , a scale-zoom can't
    otherwise be reset from Python."""
    scale = activity_scale(colors=colors) if colors else activity_scale(sorted(map(str, data["activity"].unique())))
    if len(data):
        # Span the x-axis to the time-of-day range actually present (rounded out to the hour), not a
        # fixed 00:00-24:00, so an incomplete day doesn't leave half the chart empty.
        lo = pd.Timestamp(data["start"].min()).floor("h")
        hi = pd.Timestamp(data["end"].max()).ceil("h")
        x_scale = alt.Scale(domain=[lo.isoformat(), hi.isoformat()], nice=False)
    else:
        x_scale = alt.Undefined
    zoom = alt.selection_interval(bind="scales", encodings=["x"], name=f"zoom_{zoom_key}")
    return (
        alt.Chart(data)
        .mark_bar(cornerRadius=2)
        .encode(
            x=alt.X("start:T", title=None, scale=x_scale,
                    axis=alt.Axis(format="%H:%M", labelColor="#3a3a4a", labelFontWeight=600, labelAngle=0)),
            x2="end:T",
            y=alt.Y("day:N", title=None, sort="ascending",
                    scale=alt.Scale(paddingInner=0.25),   # a small vertical gap between the day rows
                    axis=alt.Axis(labelColor="#3a3a4a", labelFontWeight=600)),
            color=alt.Color("activity:N", scale=scale, legend=None),
            tooltip=["activity", "day",
                     alt.Tooltip("start:T", title="from", format="%H:%M"),
                     alt.Tooltip("end:T", title="to", format="%H:%M")],
        )
        .add_params(zoom)
        .properties(height=height, background="transparent")
        .configure_view(fill=None, stroke=None)
        .configure_axis(grid=False, domainColor="#e6e7ec", tickColor="#e6e7ec")
    )


def activity_totals(data, colors=None, height=240):
    """One bar per activity showing the TOTAL minutes spent on it across the selected period:
    x = activity, y = total minutes, bars coloured to match the filter buttons and sorted biggest
    first. `data` is event rows with `activity` and `event_duration` (minutes); pass `colors` to
    share the buttons' palette."""
    scale = activity_scale(colors=colors) if colors else activity_scale(sorted(map(str, data["activity"].unique())))
    return (
        alt.Chart(data)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("activity:N", title=None, sort="-y",
                    axis=alt.Axis(labelAngle=0, labelColor="#3a3a4a", labelFontWeight=600)),
            y=alt.Y("sum(event_duration):Q", title="total minutes",
                    axis=alt.Axis(labelColor="#6b7280", titleColor="#6b7280")),
            color=alt.Color("activity:N", scale=scale, legend=None),
            tooltip=[alt.Tooltip("activity:N", title="activity"),
                     alt.Tooltip("sum(event_duration):Q", title="minutes", format=".0f")],
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
