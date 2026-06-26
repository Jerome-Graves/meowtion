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

import meowtion_dash as mw


def render(df, data=None):
    st.divider()

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

    # A couple of headline numbers (st.columns + st.metric).
    col1, col2, col3 = st.columns(3)
    col1.metric("Events", len(df))
    col2.metric("Minutes tracked", round(df["event_duration"].sum()))
    col3.metric("Top activity", df["activity"].value_counts().index[0])

    with st.expander("See the data table"):
        st.dataframe(df, use_container_width=True)

    # ===================================================================== #
    # STEP 2 , Pick a time window to zoom into.
    #   st.radio chooses the SPAN of the x-axis (a Day / Week / Month); st.selectbox
    #   chooses WHICH one. The options come from a helper.
    # ===================================================================== #
    st.write("### Zoom in")
    span = st.radio("X-axis spans a", ["Day", "Week", "Month"], horizontal=True)
    windows = mw.period_options(df, span)        # [(label, key), ...], newest first
    chosen_label = st.selectbox(span, [label for label, key in windows])
    chosen_key = dict(windows)[chosen_label]

    # Sleep and Resting dominate the minutes, so the small habits (eat, drink) are tiny slivers.
    # Deselecting the big ones here is how you see those small events.
    acts = sorted(df["activity"].unique())
    shown = st.multiselect("Activities (hide Sleep / Resting to see the small ones)",
                           acts, default=acts)

    # ===================================================================== #
    # STEP 3 , Keep the rows in that window (and chosen activities), then chart them STACKED BY
    #   ACTIVITY. Binning the x-axis to the hour (Day) or date (Week/Month) gives one fat bar per
    #   bucket with one label, instead of thin bars and a label repeated at every tick.
    # ===================================================================== #
    window = mw.filter_to_window(df, span, chosen_key)
    window = mw.filter_by_activity(window, shown) if shown else window.iloc[0:0]
    if window.empty:
        st.info("Nothing to show , pick another window or add activities.")
    else:
        frame = mw.over_time(window, span)
        if span == "Day":
            unit, time_unit, time_format = "hour", "yearmonthdatehours", "%H:%M"
        elif span == "Week":
            unit, time_unit, time_format = "day", "yearmonthdate", "%a %d"
        else:
            unit, time_unit, time_format = "day", "yearmonthdate", "%d"
        st.write(f"**Minutes per {unit}, by activity** , {chosen_label}")
        st.altair_chart(
            mw.stacked_bar(frame, "when", "event_duration", "activity", "minutes",
                           time_unit=time_unit, time_format=time_format, height=380),
            use_container_width=True,
        )
        # weather over the same window, so you can read the activity against hot/cold/wet days
        weather_line = mw.weather_caption(mw.window_weather(wdf, window["event_date"].unique()))
        if weather_line:
            st.caption(f"Weather this {span.lower()}:  {weather_line}")

    # ===================================================================== #
    # STEP 4 , Charts across ALL the data, each activity in its own colour.
    # ===================================================================== #
    st.write("### All activity")

    minutes_per_activity = df.groupby("activity")["event_duration"].sum().reset_index()
    st.write("**Total minutes per activity**")
    st.altair_chart(
        mw.stacked_bar(minutes_per_activity, "activity", "event_duration", "activity", "minutes",
                       legend=False),
        use_container_width=True,
    )

    times_per_activity = df["activity"].value_counts().reset_index()
    times_per_activity.columns = ["activity", "count"]
    st.write("**How often each activity happened**")
    st.altair_chart(
        mw.stacked_bar(times_per_activity, "activity", "count", "activity", "events",
                       legend=False),
        use_container_width=True,
    )

    # ===================================================================== #
    # STEP 5 , YOUR TURN. Add a chart below.
    #   `df` is everything; the mw.filter_* helpers give you a slice. For example:
    #
    #       weekend = mw.filter_by_weekday(df, ["Saturday", "Sunday"])
    #       st.bar_chart(weekend, x="event_weekday_name", y="event_duration", color="activity")
    # ===================================================================== #
