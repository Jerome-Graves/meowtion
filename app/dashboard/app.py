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

# Cat selection switcher , only shown when there's more than one collar on the account.
selected = cats[0][0] if cats else None
if len(cats) > 1:
    st.divider()
    st.subheader("🐱 Cat Selection")
    st.caption("You have more than one cat. Pick which one to view, it switches every section below.")
    names = [name for name, _ in cats]
    selected = st.segmented_control("Cat Selection", names, default=names[0],
                                    selection_mode="single", label_visibility="collapsed")
    selected = selected or names[0]   # keep a cat selected if the chip is deselected

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

# --- footer: data-safety disclosure + a cat-health resource ---
st.divider()
with st.expander("🔒 How your data is used, and how we keep it safe"):
    st.markdown(
        "Your collar's activity data belongs to you. It's stored in your own private space, and our "
        "database rules let only your signed-in account read it. We never sell it or share it with "
        "third parties, and we use it only to show you the activity and health insights on this page. "
        "You can remove a device, and its data, from the account page at any time.\n\n"
        "These insights are a helpful guide, not veterinary advice. If anything about your cat's "
        "health worries you, please speak to your vet."
    )
st.caption("Learn more about cat health and wellbeing at "
           "[International Cat Care](https://icatcare.org/), a UK feline-welfare charity.")
