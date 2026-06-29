"""Meowtion dashboard , the analytics view.   *** TEAMMATES: THIS IS YOUR FILE. ***

It's written as a step-by-step tutorial. Each STEP is one small idea, with comments explaining
the Streamlit and pandas it uses. To make a new chart, copy a step and tweak it.

You are handed a clean pandas DataFrame called `df`. You never deal with login, cookies, or
Firebase , that's all done for you. There is ONE ROW PER LOGGED EVENT, with these columns:

    cat                  the cat's name
    activity             what it was doing, e.g. "Eat", "Drink", "Resting", "Moving"
    event_date           the date, "YYYY-MM-DD"
    event_weekday_name   "Monday" ... "Sunday"
    start_time           "HH:MM"
    event_duration       how long it lasted, in MINUTES

Ready-made helpers (import meowtion_dash as mw):

    mw.health_signals(df)                       # recent vs usual for eat/drink/active/rest
    mw.period_options(df, "Week")               # the days/weeks/months you can pick from
    mw.filter_to_window(df, "Week", key)        # keep just the chosen day/week/month
    mw.over_time(window, "Week")                # minutes per hour/date, split by activity
    mw.filter_by_activity(df, "Eat")            # or a list: ["Eat", "Drink"]
    mw.stacked_bar(frame, x, y, color, title)   # bars coloured by activity (temporal=True for dates)
    mw.bar(frame, x, y, title)                  # single-colour bars
"""
import streamlit as st
import pandas as pd
import meowtion_dash as mw
import datetime


def render(df, data=None):

    # If the collar hasn't logged anything yet, `df` is empty , show a note and stop.
    if df.empty:
        st.subheader("📊 Activity history")
        st.caption("Charts appear here once the collar has logged some events.")
        return

    # Daily weather (from the station's stored history), used for context below.
    wdf = mw.weather_dataframe(data)

    # ===================================================================== #
    # STEP 1 , HEALTH WATCH , the useful bit.
    #   For each key habit, mw.health_signals compares the last few days to the cat's
    #   longer-run normal. A big change in eating or drinking is an early warning sign.
    #   st.metric(label, value, delta) shows the recent level and the % change; we keep
    #   delta_color="off" because "up" isn't always good or bad , the warnings below judge.
    # ===================================================================== #
    st.divider()
    st.subheader("🩺 Health watch")
    st.caption("How your cat's key habits compare to their normal. Big, lasting changes in eating "
               "or drinking are worth raising with your vet.")

    signals = mw.health_signals(df)
    if signals:
        cols = st.columns(len(signals))
        for col, s in zip(cols, signals):
            delta = f"{s['change_pct']:+.0f}% vs usual" if s["change_pct"] is not None else "no baseline yet"
            col.metric(f"{s['activity']}  (min/day)", f"{s['recent']:.0f}", delta=delta, delta_color="off")

        # Flag any habit that has moved a lot versus the cat's baseline.
        for s in signals:
            if s["change_pct"] is not None and abs(s["change_pct"]) >= 30:
                direction = "up" if s["change_pct"] > 0 else "down"
                st.warning(f"⚠️ **{s['activity']} is {direction} {abs(s['change_pct']):.0f}%** vs your "
                           f"cat's recent normal. Worth keeping an eye on.")

        # Weather context for the recent days , a habit change may just be the weather, not the cat.
        recent_dates = sorted(df["event_date"].unique())[-3:]
        recent_wx = mw.window_weather(wdf, recent_dates)
        if recent_wx and recent_wx["unusual"]:
            st.caption("🌡 Recently it's been " + ", ".join(recent_wx["unusual"])
                       + " , which can change how much a cat drinks, eats or rests.")
    else:
        st.caption("Not enough data yet to compare habits.")

    st.divider()
    st.subheader("📊 Activity history")
    st.caption("Browse your cat's logged activity over any day or date range.")

    # ===================================================================== #
    # STEP 2 , Pick a time window via calendar selection.
    #   Replaces the old radio buttons and selectboxes with an inline calendar picker.
    #   We create a temporary series for clean Python date object filtering.
    # ===================================================================== #
    
    today = datetime.date.today()
    pure_dates = pd.to_datetime(df["event_date"]).dt.date
    lo, hi = pure_dates.min(), pure_dates.max()
    # Default to today, but clamp into the range the data actually covers: if today is past the
    # latest logged day (or before the first), st.date_input rejects an out-of-range default.
    default_day = min(max(today, lo), hi)

    # Streamlit's default date box looks like flat text, so it isn't obvious it's clickable. Give it
    # a clear prompt and style the input as a bordered, lavender, pointer-cursor box that lifts on
    # hover, so it plainly reads as a control you can click to change the date.
    st.caption("Click the box below to pick a day, or pick a start and end date for a range.")
    st.html("""
        <style>
        div[data-testid="stDateInput"] div[data-baseweb="input"] {
            background: #ffffff;
            border: 2px solid #bc7bc2;
            border-radius: 10px;
            cursor: pointer;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            transition: border-color .15s ease, box-shadow .15s ease;
        }
        div[data-testid="stDateInput"] div[data-baseweb="input"]:hover {
            border-color: #9b59b6;
            box-shadow: 0 2px 8px rgba(188,123,194,0.40);
        }
        div[data-testid="stDateInput"] input { cursor: pointer; }
        </style>
    """)
    date_range = st.date_input(
        label="Date or date range",
        value=(default_day, default_day),
        min_value=lo,
        max_value=hi,
        label_visibility="collapsed",
    )

    # Normalise the picker result to a (start, end) day pair, then choose the x-axis granularity from
    # how many days it spans: a single calendar day is shown by HOUR; up to a week or longer by DAY.
    # (st.date_input returns a 2-tuple for a range, a 1-tuple mid-selection, or a bare date.)
    if isinstance(date_range, (tuple, list)):
        start_date, end_date = date_range[0], date_range[-1]   # a 1-tuple collapses to start == end
    else:
        start_date = end_date = date_range
    window = df[(pure_dates >= start_date) & (pure_dates <= end_date)].copy()
    span_days = (end_date - start_date).days
    if span_days == 0:
        span = "Day"          # one calendar day -> hourly x-axis
    elif span_days <= 7:
        span = "Week"         # daily x-axis
    else:
        span = "Month"        # daily x-axis

    # Sleep and Resting dominate the minutes, so the small habits (eat, drink) are tiny slivers.
    # Deselecting the big ones here is how you see those small events.
    acts = sorted(df["activity"].unique())
    # One programmatic, name-agnostic colour per activity, shared by these buttons and the chart
    # below so they always match (see meowtion_dash/charts.py).
    colours = mw.activity_colors(acts)
    shown = []

# Create columns to place the buttons side by side
    cols = st.columns(len(acts))

    for col, activity in zip(cols, acts):
        with col:
            # assign a unique memory key for this activity even if it doesnn't exist yet
            # we set the default state to True (active/on)
            state_key = f"btn_state_{activity}"
            if state_key not in st.session_state:
                st.session_state[state_key] = True
                
            #Choose the visual icon based on the active state
            # Active gets a bright checkmark, turned off gets a grey circle
            if st.session_state[state_key]:
                label_prefix = ""
                bg_colour = colours[activity]
                text_colour = mw.readable_text(bg_colour)   # black/white per colour, for legibility
                border_colour = bg_colour
            else:
                label_prefix = ""
                bg_colour = "#F4F2F7"        # muted light lavender = "off", fits the brand theme
                text_colour = "#6b7280"
                border_colour = "#DCD2E4"
            
            button_label = f"{label_prefix} {activity}"
            button_key = f"btn_click_{activity}" 
            
            button_label = activity
            # We use a clean lowercase string key for the CSS class mapping layout
            clean_id = activity.lower()
            button_key = f"btn-{clean_id}" 

            
            

            st.html(f"""
                <style>
                .st-key-btn-{clean_id} button {{
                    background-color: {bg_colour} !important;
                    color: {text_colour} !important;
                    border: 1px solid {border_colour} !important;
                    transition: background-color 0.2s ease, opacity 0.2s ease;
                }}
                .st-key-btn-{clean_id} button:hover {{
                    opacity: 0.85 !important;
                    background-color: {bg_colour} !important;
                    color: {text_colour} !important;
                }}
                </style>
            """)


             # Use the legend color for activ
            # Render the button, if clicked, flip the true/false switch in memory
            if st.button(button_label, key=button_key, use_container_width=True):
                st.session_state[state_key] = not st.session_state[state_key]
                st.rerun() # refresh the page instantly to update the icons and chart

            # If the toggle state is True, pass this activity into the chart filter
            if st.session_state[state_key]:
                shown.append(activity)



    # ===================================================================== #
    # STEP 3 , Keep the rows in that window (and chosen activities), then chart them STACKED BY
    #   ACTIVITY. If span is "Day", it processes the data at hourly steps instead of daily blocks.
    # ===================================================================== #
    window = mw.filter_by_activity(window, shown) if shown else window.iloc[0:0]

    if window.empty:
        st.info("Nothing to show , pick another window or add activities.")
    else:
        # Totals first: total minutes per activity over the selected period (x = activity, y = total
        # minutes). Driven by `window`, so it tracks the date pick and the activity filters.
        st.markdown("**Time per activity**")
        st.caption("Total minutes spent on each activity over the chosen dates. "
                   "Use the coloured buttons above to turn activities on or off in both charts.")
        st.altair_chart(mw.activity_totals(window, colors=colours), use_container_width=True)

        # ONE timeline for any span: rows of days (y-axis), time of day on the x-axis (00:00-24:00),
        # each event a horizontal bar at the time of day it happened. A single day is simply one row,
        # so the single-day and multi-day views look and behave the same. Include the day BEFORE the
        # range too, so an overnight episode that started before it still fills the first day's early
        # hours; then keep only the days inside the selected range.
        ext = df[(pure_dates >= start_date - datetime.timedelta(days=1)) & (pure_dates <= end_date)]
        ext = mw.filter_by_activity(ext, shown)
        frame = mw.daily_segments(ext)
        frame = frame[(frame["day"] >= start_date.isoformat()) & (frame["day"] <= end_date.isoformat())]
        if span != "Day":
            frame = mw.trim_sparse_edge_days(frame)   # multi-day: hide incomplete leading/trailing days
        if frame.empty:
            st.info("No activity logged in this window.")
        else:
            n_days = frame["day"].nunique()
            st.markdown("**When activities happened**")
            st.caption("Each bar is an activity at the time of day it occurred. Scroll or drag to zoom the time axis.")
            zoom_n = st.session_state.get("timeline_zoom_n", 0)
            st.altair_chart(
                mw.event_timeline(frame, colors=colours,
                                  height=max(220, 40 + 26 * n_days), zoom_key=zoom_n),
                use_container_width=True,
                key=f"timeline_{zoom_n}",
            )
            # Reset zoom, centered below the chart. Bumping this counter renames the zoom selection,
            # which remounts the chart at the full view (a scale-zoom can't otherwise be reset), so
            # rerun once so the chart picks up the new key.
            _, mid, _ = st.columns([2, 1, 2])
            if mid.button("↺ Reset view", key="reset_timeline_zoom",
                          help="Zoom back out to the full day", use_container_width=True):
                st.session_state["timeline_zoom_n"] = zoom_n + 1
                st.rerun()

    # weather over the same window, so you can read the activity against hot/cold/wet days
    if not window.empty:
        weather_line = mw.weather_caption(mw.window_weather(wdf, window["event_date"].unique()))
        if weather_line:
            st.caption(f"Weather this period:  {weather_line}")
        
    # ===================================================================== #
    # STEP 4 , Recent activity for troubleshooting.
    # ===================================================================== #
