"""Teammate sandbox - your Streamlit-tutorial charts, kept OUT of the live dashboard.

This file is NOT run by the app (Streamlit only runs app.py and pages/). It is here so your
experimental charts are preserved. The live, working charts are in app.py under the
"TEAMMATE: add your own charts here" marker - add yours there to see them on the dashboard.

To run the code below you would need `df` (the activity DataFrame) and `import altair as alt`.
Note: st.select_slider needs >=2 distinct values (use st.selectbox if a column may have one).
"""

st.subheader("⏱️ Activity Duration Chart")

# Try making a slider to filter the chart by day name

day_filter = st.select_slider(
    "Filter by Day of the Week",
    options=df['event_weekday_name'].unique().tolist(),
    value=df[['event_weekday_name']].iloc[0, 0]
)

# Create a chart to show how the cat spent their day like a gant chart

st.bar_chart(
    df, 
    x='start_time', 
    y='activity', 
    use_container_width=True,
    x_label='Day',
    y_label='Activity',
    color='activity',
    stack=True
    )
# ============================================================================
# STEP 7: CREATE ANOTHER CHART - Activity Frequency
# ============================================================================
# This chart shows how many times each activity happened
st.subheader("Weekly Activity Frequency")
# Make a bar chart which shows the total duration of each activity per weekday
st.bar_chart(
    df,
    x='event_weekday_name',
    y='event_duration',
    x_label='Weekday',
    y_label='Total Duration (mins)',
    color='activity',
    sort='event_date',
    horizontal=True
)


st.subheader("🔄 Activity Frequency")

# Count how many times each activity appears in the data
# .value_counts() counts occurrences of each activity
activity_counts = df['activity'].value_counts().reset_index()
activity_counts.columns = ['activity', 'count']

# Create a bar chart of activity frequency
frequency_chart = alt.Chart(activity_counts).mark_bar().encode(
    x='count',
    y='activity',
    color=alt.Color('count', scale=alt.Scale(scheme='viridis')),  # Nice colors!
).properties(
    width=600,
    height=300,
    title="How many times did the cat do each activity?"
)

st.altair_chart(frequency_chart, use_container_width=True)

# ============================================================================
# Done! That's the basics of Streamlit!
# ============================================================================
#
# KEY CONCEPTS YOU LEARNED:
# 1. st.title() - Add a title
# 2. st.write() - Add text
# 3. st.dataframe() - Display a table
# 4. st.subheader() - Add a section heading
# 5. st.metric() - Show a single metric
# 6. st.columns() - Create side-by-side columns
# 7. st.altair_chart() - Display a chart
# 8. pd.DataFrame() - Create a table from data
# 9. alt.Chart() - Create an interactive chart
#
# NEXT STEPS TO LEARN:
# - Try st.slider() to filter data
# - Try st.selectbox() to pick activities
# - Try st.line_chart() for line charts
# - Read the Streamlit documentation at streamlit.io
# ============================================================================