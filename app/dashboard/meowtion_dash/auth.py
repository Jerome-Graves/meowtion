"""Sign-in: read the login cookie that account.html set, resolve who the viewer is, and
render the signed-in header (or the sign-in gate). All cookie / JWT handling lives here, so
the rest of the app just calls require_session() and gets (uid, token, is_demo).

Trust comes from the database rules, not this code: a real token reads only its owner; the
demo account is world-readable but write-locked, so the demo is genuinely read-only.
"""
import base64
import html
import json
import time

import streamlit as st
import extra_streamlit_components as stx

_ACCOUNT_URL = "app/static/account.html"


def _jwt_payload(t):
    body = t.split(".")[1]
    body += "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(body))


def _account_link(label, url=_ACCOUNT_URL):
    # A raw <a target="_self"> navigates in the SAME tab (st.link_button / markdown links force
    # a new tab). Styled as a theme-adaptive outline button.
    st.markdown(
        f'<a href="{url}" target="_self" '
        'style="display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;'
        'padding:0.45rem 0.85rem;border:1px solid rgba(128,128,128,0.4);border-radius:0.5rem;'
        'background:transparent;color:inherit;text-decoration:none;font-weight:400;">'
        f"{label}</a>",
        unsafe_allow_html=True,
    )


def _signed_in_header(claims):
    uid = claims.get("user_id") or claims.get("sub")
    # Streamlit auto-linkifies a bare "name@domain" into a mailto: link; a zero-width space after
    # the "@" breaks that pattern (invisible) while the email still reads normally.
    email = html.escape(str(claims.get("email", uid))).replace("@", "@​")   # escape + ZWSP stops mailto auto-link
    btn = ("display:inline-flex;align-items:center;justify-content:center;padding:0.4rem 0.85rem;"
           "border:1px solid rgba(128,128,128,0.4);border-radius:0.5rem;background:transparent;"
           "color:inherit;text-decoration:none;font-weight:400;white-space:nowrap;")
    st.markdown(
        '<div style="display:flex;align-items:center;gap:0.6rem;margin:0 0 0.6rem;">'
        f'<span style="flex:1;color:rgba(133,133,143,0.95);font-size:0.85rem;">Signed in as <strong style="color:inherit;font-weight:700;">{email}</strong></span>'
        f'<a href="{_ACCOUNT_URL}" target="_self" style="{btn}">Manage devices</a>'
        f'<a href="{_ACCOUNT_URL}?logout=1" target="_self" style="{btn}">Log out</a>'
        '</div>',
        unsafe_allow_html=True,
    )
    return uid


def require_session():
    """Resolve the viewer and render the appropriate header. Returns (uid, token, is_demo).

    Signed out, this renders the sign-in gate and calls st.stop() (never returns).
    """
    # Streamlit Community Cloud doesn't expose browser cookies to the server, so we read the
    # cookie account.html set with a CLIENT-SIDE component. It answers asynchronously and returns
    # {} until it has reported the browser's cookies (indistinguishable from "signed out"), so we
    # poll a few times before giving up - a signed-in user resolves the instant the cookie arrives.
    cookies = stx.CookieManager().get_all() or {}
    if cookies:
        st.session_state["_cookie_tries"] = 0
    elif st.session_state.get("_cookie_tries", 0) < 15:   # up to ~3 s
        st.session_state["_cookie_tries"] = st.session_state.get("_cookie_tries", 0) + 1
        st.info("Loading…")
        time.sleep(0.2)
        st.rerun()

    token = cookies.get("mtoken")
    demo_uid = cookies.get("mdemo")

    if token:
        claims = _jwt_payload(token)
        uid = _signed_in_header(claims)
        return uid, token, False

    if demo_uid:
        st.caption(f"👀 Demo · read-only  ·  [exit]({_ACCOUNT_URL})")
        return demo_uid, None, True

    # Not signed in: show a reliable sign-in link (a meta-refresh redirect loops on Community Cloud).
    st.warning("Please sign in to view your dashboard.")
    _account_link("Sign in")
    st.stop()
