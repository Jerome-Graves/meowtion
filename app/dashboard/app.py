"""Meowtion dashboard , entry point.

This file is intentionally thin: it just wires the pieces together in order. All the
plumbing (cookies, JWT, Firebase reads, data formatting) lives in the `meowtion_dash`
package, and the editable analytics dashboard is `dashboard_view.py`.

  TEAMMATES: you want dashboard_view.py , not this file.

Flow:
    theme  ->  sign-in  ->  collar switcher  ->  current activity  ->  health watch +
    activity history  ->  recent activity
"""
import streamlit as st

import meowtion_dash as mw
import dashboard_view

mw.configure_page()        # set_page_config , must be the first Streamlit call
mw.brand_header()          # logo + wordmark + page theme

# Resolve the viewer from the login cookie. Renders the signed-in header (or the demo
# caption); if signed out it shows the sign-in gate and stops here.
uid, token, is_demo = mw.require_session()

# One cached read of the owner's data, shared with the live view's fragment below.
status, data = mw.fetch(uid, token)
cats = mw.list_cats(data)                          # [(name, cat_id), ...]

# Active-cat switcher , only shown when there's more than one collar on the account.
selected = cats[0][0] if cats else None
if len(cats) > 1:
    selected = st.radio("**Active cat**", [name for name, _ in cats], horizontal=True)

# Current-activity card (live) , top, right under the switcher.
mw.live_view(uid, token, only_cat=selected, part="current")

# Activity-history dashboard (the part teammates edit): health watch + history charts.
# Wrapped in an auto-refreshing fragment, like the live cards above and below, so the charts update
# on their own instead of only when the user interacts. It re-reads the cached fetch(), so new
# events appear automatically once that read's TTL lapses.
@st.fragment(run_every=30)
def _history():
    _, hdata = mw.fetch(uid, token)
    hdf = mw.activity_dataframe(hdata, mw.model_labels(hdata))
    if selected is not None:
        hdf = hdf[hdf["cat"] == selected]
    dashboard_view.render(hdf, hdata)

_history()

# Recent-activity list (live) , bottom.
mw.live_view(uid, token, only_cat=selected, part="recent")
