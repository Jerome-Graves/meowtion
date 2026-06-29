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

    date_range = st.date_input(
        label="📅 Select a date or date range",
        value=(default_day, default_day),
        min_value=lo,
        max_value=hi,
    )

    # Determine whether a range or a single date was chosen, and configure the time span
    if isinstance(date_range, tuple) and len(date_range) == 2 and date_range[0] != date_range[1]:
        start_date, end_date = date_range
        window = df[(pure_dates >= start_date) & (pure_dates <= end_date)].copy()
        span = "Week" if (end_date - start_date).days <= 7 else "Month"
    elif isinstance(date_range, tuple) and len(date_range) == 1 or date_range[0] == date_range[1]:
        start_date = date_range[0]
        window = df[pure_dates == start_date].copy()
        span = "Day"
    elif isinstance(date_range, pd.Timestamp) or hasattr(date_range, 'year'):
        # Fallback handle if Streamlit returns a single bare date object instead of a tuple
        start_date = date_range
        window = df[pure_dates == start_date].copy()
        span = "Day"
    else:
        window = df.copy()
        span = "Month"

    # Sleep and Resting dominate the minutes, so the small habits (eat, drink) are tiny slivers.
    # Deselecting the big ones here is how you see those small events.
    LEGEND_COLORS = {
        "Eating": "#2ca02c",      # Legend Green
        "Drinking": "#1f77b4",    # Legend Blue
        "Resting": "#ff7f0e",  # Legend Orange
        "Moving": "#9467bd",   # Legend Purple
        "Grooming": "#e377c2"  # Legend Pink
    }    
    acts = sorted(df["activity"].unique())
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
                bg_colour = LEGEND_COLORS.get(activity, "#1f77b4")
                text_colour = "#FFFFFF"
                border_colour = bg_colour
            else:
                label_prefix = ""
                bg_colour = "#F0FAF6"
                text_colour = "#000000"
                border_colour = "#E0EF52"
            
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
        if span == "Day":
            # --- HOURLY VIEW STRATEGY ---
            # Safe: Cleanly combine string date and string start_time ("HH:MM")
            combined_datetime = window["event_date"].astype(str) + " " + window["start_time"].astype(str)
            window["when"] = pd.to_datetime(combined_datetime)
            
            # Group by hourly intervals and activity type
            frame = window.groupby([pd.Grouper(key="when", freq="h"), "activity"])["event_duration"].sum().reset_index()
            
            unit, time_unit, time_format = "hour", "yearmonthdatehours", "%H:%M"
            chosen_label = start_date.strftime("%B %d, %Y")
        else:
            # --- DAILY VIEW STRATEGY ---
            frame = mw.over_time(window, span)
            if span == "Week":
                unit, time_unit, time_format = "day", "yearmonthdate", "%a %d"
            else:
                unit, time_unit, time_format = "day", "yearmonthdate", "%d"
            
            # Handle label ranges for printing strings cleanly
            if isinstance(date_range, tuple) and len(date_range) == 2:
                chosen_label = f"{date_range[0].strftime('%b %d')} - {date_range[1].strftime('%b %d, %Y')}"
            else:
                chosen_label = "Selected Window"

        # Skip the chart when the window has nothing to plot. Handing Vega an empty (or all-zero)
        # dataset makes it warn "Infinite extent for field ..." and renders a blank axis.
        if frame.empty or frame["event_duration"].fillna(0).sum() == 0:
            st.info("No activity logged in this window.")
        else:
            st.altair_chart(
                mw.stacked_bar(frame, "when", "event_duration", "activity", "minutes",
                               time_unit=time_unit, time_format=time_format, height=380, legend=False),
                use_container_width=True,
            )

    # weather over the same window, so you can read the activity against hot/cold/wet days
    if not window.empty:
        weather_line = mw.weather_caption(mw.window_weather(wdf, window["event_date"].unique()))
        if weather_line:
            st.caption(f"Weather this period:  {weather_line}")
        
    # ===================================================================== #
    # STEP 4 , Recent activity for troubleshooting.
    # ===================================================================== #
