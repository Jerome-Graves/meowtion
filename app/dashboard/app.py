"""Meowtion dashboard , entry point.

This file is intentionally thin: it just wires the pieces together in order. All the
plumbing (cookies, JWT, Firebase reads, data formatting) lives in the `meowtion_dash`
package, and the editable analytics dashboard is `dashboard_view.py`.

  TEAMMATES: you want dashboard_view.py , not this file.

Flow:
    theme  ->  sign-in  ->  live cards  ->  activity-history dashboard
"""
import meowtion_dash as mw
import dashboard_view

mw.configure_page()        # set_page_config , must be the first Streamlit call
mw.brand_header()          # logo + wordmark + page theme

# Resolve the viewer from the login cookie. Renders the signed-in header (or the demo
# caption); if signed out it shows the sign-in gate and stops here.
uid, token, is_demo = mw.require_session()

# Live, auto-refreshing "current state" cards for each cat.
mw.live_view(uid, token)

# Activity-history dashboard (the part teammates edit). Hand it a clean DataFrame.
status, data = mw.fetch(uid, token)        # cached , same read the live view uses
df = mw.activity_dataframe(data, mw.model_labels(data))
dashboard_view.render(df, data)
