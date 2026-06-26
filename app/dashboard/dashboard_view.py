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
    mw.filter_by_weekday(df, "Saturday")        # or ["Saturday", "Sunday"]
    mw.totals_by_period(df, "Day")              # sum minutes per "Day" / "Week" / "Month"
    mw.bar(frame, x, y, title)                  # a branded bar chart (add temporal=True for dates)
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
    col1.metric("Episodes", len(df))                                   # how many rows
    col2.metric("Minutes tracked", round(df["event_duration"].sum()))  # add up the minutes column
    col3.metric("Top activity", df["activity"].value_counts().index[0])  # most frequent activity

    # A fun headline , just to show you can do maths on the data.
    hours = round(df["event_duration"].sum() / 60)
    st.caption(f"😼 {hours} hours of world domination logged so far.")

    # st.expander hides the raw table behind a click, so it doesn't clutter the page.
    with st.expander("See the data table"):
        st.dataframe(df, use_container_width=True)

    # ===================================================================== #
    # STEP 2 , Add controls the viewer can change.
    #   st.radio       , pick ONE option (here: the time period).
    #   st.multiselect , pick MANY options (here: which activities to include).
    #   Whatever they pick comes back as a normal Python value you can use below.
    # ===================================================================== #
    st.write("### Choose what to show")

    period = st.radio("Group by", ["Day", "Week", "Month"], horizontal=True)

    all_activities = sorted(df["activity"].unique())
    chosen = st.multiselect("Activities", all_activities, default=all_activities)

    # ===================================================================== #
    # STEP 3 , Filter the data to what the viewer chose.
    #   mw.filter_by_activity takes the DataFrame and returns a smaller DataFrame.
    # ===================================================================== #
    filtered = mw.filter_by_activity(df, chosen) if chosen else df.iloc[0:0]
    st.caption(f"Showing {len(filtered)} of {len(df)} episodes.")

    # ===================================================================== #
    # STEP 4 , Chart the FILTERED data over time.
    #   mw.totals_by_period adds up the minutes per Day / Week / Month for you.
    #   mw.bar(..., temporal=True) draws a date-axis bar chart in the app's colours.
    # ===================================================================== #
    if not filtered.empty:
        over_time = mw.totals_by_period(filtered, period)
        st.write(f"**Minutes per {period.lower()}**")
        st.altair_chart(
            mw.bar(over_time, "period", "event_duration", "minutes", temporal=True),
            use_container_width=True,
        )

    # ===================================================================== #
    # STEP 5 , Charts on ALL the data (no filtering).
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
