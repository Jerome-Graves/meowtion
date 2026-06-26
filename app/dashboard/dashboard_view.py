"""Meowtion dashboard , the analytics view.   *** TEAMMATES: THIS IS YOUR FILE. ***

It's written as a step-by-step tutorial. Each STEP is one small idea, with comments explaining
the Streamlit and pandas it uses. To make a new chart, copy a step and tweak it.

You are handed a clean pandas DataFrame called `df`. You never deal with login, cookies, or
Firebase , that's all done for you. There is ONE ROW PER LOGGED EPISODE, with these columns:

    cat                  the cat's name
    activity             what it was doing, e.g. "Eat", "Drink", "Resting", "Moving"
    event_date           the date, "YYYY-MM-DD"
    event_weekday_name   "Monday" ... "Sunday"
    start_time           "HH:MM"
    event_duration       how long it lasted, in MINUTES

Ready-made helpers (we did the fiddly bits for you):

    import meowtion_dash as mw
    mw.filter_by_activity(df, "Eat")            # or a list: ["Eat", "Drink"]
    mw.period_options(df, "Week")               # the weeks (or days/months) you can pick from
    mw.filter_to_window(df, "Week", key)        # keep just the chosen day/week/month
    mw.over_time(window, "Week")                # minutes along the x-axis (per hour / per day)
    mw.bar(frame, x, y, title)                  # a branded bar chart (temporal=True for dates)
"""
import streamlit as st

import meowtion_dash as mw


def render(df, data=None):
    st.divider()
    st.subheader("📊 Activity history")

    # If the collar hasn't logged anything yet, `df` is empty , show a note and stop.
    if df.empty:
        st.caption("Charts appear here once the collar has logged some episodes.")
        return

    # ===================================================================== #
    # STEP 1 , Show a few headline numbers.
    #   st.columns(3) makes three slots side by side.
    #   st.metric(label, value) shows one big number in a slot.
    # ===================================================================== #
    col1, col2, col3 = st.columns(3)
    col1.metric("Episodes", len(df))                                     # how many rows
    col2.metric("Minutes tracked", round(df["event_duration"].sum()))    # sum the minutes column
    col3.metric("Top activity", df["activity"].value_counts().index[0])  # most frequent activity

    # A fun headline , just to show you can do maths on the data.
    hours = round(df["event_duration"].sum() / 60)
    st.caption(f"😼 {hours} hours of world domination logged so far.")

    with st.expander("See the data table"):     # st.expander hides this until clicked
        st.dataframe(df, use_container_width=True)

    # ===================================================================== #
    # STEP 2 , Pick a time window to zoom into.
    #   First choose the SPAN of the x-axis (a Day, a Week, or a Month) with st.radio,
    #   then choose WHICH one with st.selectbox. The options come from a helper.
    # ===================================================================== #
    st.write("### Zoom in")

    span = st.radio("X-axis spans a", ["Day", "Week", "Month"], horizontal=True)

    windows = mw.period_options(df, span)        # [(label, key), ...], newest first
    labels = [label for label, key in windows]
    chosen_label = st.selectbox(span, labels)    # e.g. "Week of 23 Jun 2025"
    chosen_key = dict(windows)[chosen_label]     # the matching key for the helper below

    # (optional) also let the viewer narrow to certain activities
    all_activities = sorted(df["activity"].unique())
    chosen_acts = st.multiselect("Activities", all_activities, default=all_activities)

    # ===================================================================== #
    # STEP 3 , Keep just the rows in that window (and those activities).
    # ===================================================================== #
    window = mw.filter_to_window(df, span, chosen_key)
    window = mw.filter_by_activity(window, chosen_acts) if chosen_acts else window.iloc[0:0]
    st.caption(f"{len(window)} episodes in {chosen_label}.")

    # ===================================================================== #
    # STEP 4 , Chart that window.
    #   mw.over_time sums the minutes per hour (for a Day) or per date (Week / Month).
    #   We label the x-axis with hours for a Day, otherwise with dates.
    # ===================================================================== #
    if window.empty:
        st.info("No activity in this window , pick another, or add more activities.")
    else:
        frame = mw.over_time(window, span)
        unit = "hour" if span == "Day" else "day"
        time_format = "%H:%M" if span == "Day" else "%d %b"
        st.write(f"**Minutes per {unit}** , {chosen_label}")
        st.altair_chart(
            mw.bar(frame, "when", "event_duration", "minutes", temporal=True, time_format=time_format),
            use_container_width=True,
        )

    # ===================================================================== #
    # STEP 5 , Charts across ALL the data (ignoring the window above).
    #   df.groupby("activity")["event_duration"].sum() adds up minutes per activity.
    #   df["activity"].value_counts() counts how many times each activity happened.
    # ===================================================================== #
    st.write("### All activity")

    minutes_per_activity = df.groupby("activity")["event_duration"].sum().reset_index()
    st.write("**Total minutes per activity**")
    st.altair_chart(
        mw.bar(minutes_per_activity, "activity", "event_duration", "minutes"),
        use_container_width=True,
    )

    times_per_activity = df["activity"].value_counts().reset_index()
    times_per_activity.columns = ["activity", "count"]
    st.write("**How often each activity happened**")
    st.altair_chart(
        mw.bar(times_per_activity, "activity", "count", "episodes"),
        use_container_width=True,
    )

    # ===================================================================== #
    # STEP 6 , YOUR TURN. Add a chart below.
    #   `df` is everything; the mw.filter_* helpers give you a slice. For example:
    #
    #       weekend = mw.filter_by_weekday(df, ["Saturday", "Sunday"])
    #       st.bar_chart(weekend, x="event_weekday_name", y="event_duration", color="activity")
    # ===================================================================== #
