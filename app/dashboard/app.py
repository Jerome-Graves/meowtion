"""Meowtion dashboard , entry point.

This file is intentionally thin: it just wires the pieces together in order. All the
plumbing (cookies, JWT, Firebase reads, data formatting) lives in the `meowtion_dash`
package, and the editable analytics dashboard is `dashboard_view.py`.

  TEAMMATES: you want dashboard_view.py , not this file.

Flow:
    theme  ->  sign-in  ->  collar switcher  ->  live cards  ->  activity-history dashboard
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

# Collar switcher , only shown when there's more than one collar on the account.
selected = cats[0][0] if cats else None
if len(cats) > 1:
    selected = st.radio("Collar", [name for name, _ in cats], horizontal=True)

# Live, auto-refreshing "current state" cards for the selected collar.
mw.live_view(uid, token, only_cat=selected)

# Activity-history dashboard (the part teammates edit), scoped to the selected collar.
df = mw.activity_dataframe(data, mw.model_labels(data))
if selected is not None:
    df = df[df["cat"] == selected]
dashboard_view.render(df, data)
