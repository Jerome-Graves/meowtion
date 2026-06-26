"""Meowtion dashboard , the analytics view.

TEAMMATES: THIS IS YOUR FILE. Edit it freely. You do NOT need to touch login, cookies, or
the Firebase format , that is all handled for you. You are handed a clean pandas DataFrame.

`df` has one row per logged activity episode:

    cat | activity | event_date | event_weekday_name | start_time | event_duration

  - activity            e.g. "Eat", "Drink", "Resting", "Moving"
  - event_date          "YYYY-MM-DD"
  - event_weekday_name  "Monday" ... "Sunday"
  - start_time          "HH:MM"
  - event_duration      minutes (float)

Ready-made helpers (import meowtion_dash as mw):

    mw.filter_by_activity(df, "Eat")                 mw.filter_by_activity(df, ["Eat", "Drink"])
    mw.filter_by_weekday(df, "Saturday")
    mw.filter_by_date_range(df, start="2026-06-01", end="2026-06-30")
    mw.last_n_days(df, 7)
    mw.bar(frame, x, y, y_title)                      a branded Altair bar chart

Everything is plain Streamlit + pandas, so beginner-tutorial chart code works here unchanged.
Add your own charts in the marked area at the bottom.
"""
import streamlit as st

import meowtion_dash as mw


def render(df, data=None):
    """Render the activity-history dashboard. `df` is the clean activity DataFrame;
    `data` is the raw Firebase JSON, available if you ever need something not in `df`."""
    st.divider()
    st.subheader("📊 Activity history")

    if df.empty:
        st.caption("Charts appear here once the collar has logged some episodes.")
        return

    # ---- headline numbers, straight off the DataFrame ----
    c1, c2, c3 = st.columns(3)
    c1.metric("Episodes", len(df))
    c2.metric("Minutes tracked", round(df["event_duration"].sum()))
    c3.metric("Most common", df["activity"].value_counts().index[0])

    # a cheeky headline (example of computing on the data with a filter helper)
    total_h = round(df["event_duration"].sum() / 60)
    rest_h = round(mw.filter_by_activity(df, "Resting")["event_duration"].sum() / 60)
    st.markdown(f"#### 😼 World-domination progress: **{total_h} h** logged "
                f"— _{rest_h} h of it strategic resting._")

    with st.expander("See the raw data table"):
        st.dataframe(df, use_container_width=True)

    # =====================================================================
    # PART 1 , FILTER the data, then chart the FILTERED result
    # =====================================================================
    st.write("### Filter")
    activities = sorted(df["activity"].unique())
    picked = st.multiselect("Activities to include", activities, default=activities)
    days_present = [d for d in
                    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                    if d in set(df["event_weekday_name"])]
    day = st.selectbox("Weekday", ["All days"] + days_present)

    fdf = mw.filter_by_activity(df, picked) if picked else df.iloc[0:0]
    if day != "All days":
        fdf = mw.filter_by_weekday(fdf, day)
    st.caption(f"{len(fdf)} of {len(df)} episodes match your filter.")

    if not fdf.empty:
        # easy chart on the FILTERED data: minutes per day
        per_day = fdf.groupby("event_date")["event_duration"].sum().reset_index()
        st.write("**Minutes per day** (filtered)")
        st.bar_chart(per_day, x="event_date", y="event_duration", color="#bc7bc2")

    # =====================================================================
    # PART 2 , charts on the FULL (raw) data , no filtering
    # =====================================================================
    st.write("### All activity")

    # total minutes per activity (branded bar helper)
    by_activity = df.groupby("activity")["event_duration"].sum().reset_index()
    st.write("**Total minutes per activity**")
    st.altair_chart(mw.bar(by_activity, "activity", "event_duration", "minutes"),
                    use_container_width=True)

    # how often each activity happened (branded bar helper)
    counts = df["activity"].value_counts().reset_index()
    counts.columns = ["activity", "count"]
    st.write("**How often each activity happened**")
    st.altair_chart(mw.bar(counts, "activity", "count", "episodes"),
                    use_container_width=True)

    # =====================================================================
    # 👇 TEAMMATE: add your own charts below.
    #    Use `df` for everything, or a filter helper for a slice, e.g.:
    #        weekend = mw.filter_by_weekday(df, ["Saturday", "Sunday"])
    #        st.bar_chart(weekend, x="event_weekday_name", y="event_duration", color="activity")
    # =====================================================================
