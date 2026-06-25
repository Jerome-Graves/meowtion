"""Meowtion dashboard (Python / Streamlit).

Login lives on the static JS page (static/account.html), which drops the Firebase
token in a same-origin cookie (mtoken), or a demo flag (mdemo) for the read-only public
demo. This page reads whichever applies and shows the owner's cats. Trust comes from the
database rules: a real token reads only its owner; the demo account is world-readable but
write-locked, so the demo is genuinely read-only.
"""
import base64
import datetime
import json
import time

import requests
import streamlit as st
import extra_streamlit_components as stx

st.set_page_config(page_title="Meowtion", page_icon="🐾")
st.title("🐾 Meowtion")


def jwt_payload(t):
    body = t.split(".")[1]
    body += "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(body))


def account_link(label, container=st, url="app/static/account.html"):
    # st.link_button and markdown links force target=_blank (a NEW tab); a raw anchor with
    # target=_self navigates in the SAME tab. Styled as an outline button (theme-adaptive colours).
    html = (
        f'<a href="{url}" target="_self" '
        'style="display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;'
        'padding:0.45rem 0.85rem;border:1px solid rgba(128,128,128,0.4);border-radius:0.5rem;'
        'background:transparent;color:inherit;text-decoration:none;font-weight:400;">'
        f"{label}</a>"
    )
    container.markdown(html, unsafe_allow_html=True)


# Streamlit Community Cloud does not expose browser cookies to the server (st.context.cookies is
# empty there), so we read the login cookie account.html set with a CLIENT-SIDE component instead.
# CookieManager reads document.cookie in the browser and reports it back to Python; on the very
# first run it may be empty, then the component triggers a rerun where the value is present.
cookie_manager = stx.CookieManager()
cookies = cookie_manager.get_all() or {}
# CookieManager answers asynchronously and returns {} until it has reported the browser's cookies,
# which is indistinguishable from "signed out". Poll: keep showing a loading state and rerunning
# until it reports something - a signed-in user resolves the instant the cookie arrives, with no
# flash - or until a short timeout, after which persistent emptiness is treated as signed out.
if cookies:
    st.session_state["_cookie_tries"] = 0
elif st.session_state.get("_cookie_tries", 0) < 15:   # up to ~3s waiting for the component to answer
    st.session_state["_cookie_tries"] = st.session_state.get("_cookie_tries", 0) + 1
    st.info("Loading…")
    time.sleep(0.2)
    st.rerun()
token = cookies.get("mtoken")
demo_uid = cookies.get("mdemo")

if token:
    claims = jwt_payload(token)
    uid = claims.get("user_id") or claims.get("sub")
    # Show the email as plain text. Streamlit's markdown auto-linkifies a bare "name@domain" into a
    # mailto: link; a zero-width space after the "@" breaks that pattern (invisible, verified) while
    # the email still displays normally.
    email = str(claims.get("email", uid)).replace("@", "@​")
    # One flexbox row keeps the caption and both buttons aligned (st.columns + markdown anchors don't
    # line up cleanly). Both buttons are raw <a target="_self"> so they open in the SAME tab; Log out
    # goes to the login page with ?logout, which signs out of Firebase and shows the login form.
    btn = ("display:inline-flex;align-items:center;justify-content:center;padding:0.4rem 0.85rem;"
           "border:1px solid rgba(128,128,128,0.4);border-radius:0.5rem;background:transparent;"
           "color:inherit;text-decoration:none;font-weight:400;white-space:nowrap;")
    st.markdown(
        '<div style="display:flex;align-items:center;gap:0.6rem;margin:0 0 0.6rem;">'
        f'<span style="flex:1;color:rgba(133,133,143,0.95);font-size:0.85rem;">Signed in as {email}</span>'
        f'<a href="app/static/account.html" target="_self" style="{btn}">Manage devices</a>'
        f'<a href="app/static/account.html?logout=1" target="_self" style="{btn}">Log out</a>'
        '</div>',
        unsafe_allow_html=True,
    )
elif demo_uid:
    uid, token = demo_uid, None   # public read, no auth - read-only demo
    st.caption("👀 Demo · read-only  ·  [exit](app/static/account.html)")
else:
    # Not signed in: gate to the login page. (A meta-refresh auto-redirect works locally but loops /
    # hangs on Streamlit Community Cloud, so we show a reliable sign-in link instead of redirecting.)
    st.warning("Please sign in to view your dashboard.")
    account_link("Sign in")
    st.stop()

try:
    DB_URL = st.secrets["db_url"]
except Exception:
    DB_URL = "https://meowtion-app-default-rtdb.europe-west1.firebasedatabase.app"

EVENT_ICON = {"sleep": "😴", "rest": "🛋", "active": "🐾", "walk": "🚶", "play": "🧶",
              "groom": "🧼", "drink": "💧", "eat": "🍽", "purr": "💜"}


def fmt_time(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%d %b · %H:%M")   # date + time


def fmt_dur(s):
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


@st.cache_data(ttl=10)   # one DB read per 10 s, shared across all viewers (incl. all demo users)
def fetch(uid, token):
    params = {"auth": token} if token else {}
    r = requests.get(f"{DB_URL}/users/{uid}.json", params=params, timeout=10)
    return r.status_code, (r.json() if r.ok else None)


@st.fragment(run_every=10)   # re-run every 10 s so live data + online/offline stay current
def show():
    status, data = fetch(uid, token)
    if status == 401:
        st.error("Session expired , please sign in again.")
        return

    devices = (data or {}).get("devices", {})
    # The trained model's class names (set by the train function). The collar reports a class INDEX
    # in its telemetry (v2); we map it to the action name here, so the collar stays label-agnostic.
    model_labels = (data or {}).get("models", {}).get("labels") or []
    now_ms = time.time() * 1000
    found = False

    for tok, station in devices.items():
        sname = station.get("name", "station")
        weather = (station.get("weather") or {}).get("current")
        for cat_id, cat in (station.get("cats") or {}).items():
            found = True
            cur = cat.get("current", {})
            ts = cur.get("ts")
            fresh = isinstance(ts, (int, float)) and (now_ms - ts) < 35000

            # prefer the friendly name the owner set when registering (the collar's registry
            # entry), not the id the station relays under
            cat_name = (devices.get(cat_id) or {}).get("name") or cat.get("name") or cat_id
            # Telemetry v2 (cur["ver"] == 2) = REAL on-device classification: cur["cls"] is the class
            # index into the trained model's labels, cur["conf"] is the confidence. v1 (or no model yet)
            # is the collar's simulated state machine, shown as a plain state label.
            real = cur.get("ver") == 2
            detected = None
            if real:
                cls = cur.get("cls")
                if isinstance(cls, int) and 0 <= cls < len(model_labels):
                    detected = model_labels[cls]

            st.subheader(f"🐈 {cat_name}")
            st.caption(("🟢 online" if fresh else "⚪ offline")
                       + ("  ·  🧠 detecting on-device" if real else "")
                       + f"  ·  via {sname}")

            c1, c2, c3 = st.columns(3)
            if real:
                conf = cur.get("conf")
                ic = EVENT_ICON.get(detected, "🧠")
                c1.metric("Detected", f"{ic} {detected}" if detected else "🧠 …",
                          delta=(f"{conf}%" if isinstance(conf, int) else None), delta_color="off")
            else:
                c1.metric("State", cur.get("state", "—"))
            c2.metric("Steps", cur.get("steps", "—"))
            batt = cur.get("battery")
            c3.metric("Battery", f"{batt}%" if batt is not None else "—")

            events = sorted((cat.get("events") or {}).values(),
                            key=lambda e: e.get("start", 0), reverse=True)
            if events:
                st.write("**Recent activity**")
                for e in events[:8]:
                    ic = EVENT_ICON.get(e.get("type"), "•")
                    st.write(f"{ic} {e.get('type', '?')}  ·  {fmt_time(e.get('start', 0))}  ·  {fmt_dur(e.get('durationSec', 0))}")

            if weather:
                rain = " · raining" if weather.get("raining") else ""
                st.caption(f"🌤 {weather.get('tempC', '?')}°C · {weather.get('condition', '?')}{rain}")
            st.divider()

    if not found:
        st.info("No cats yet. On the account page, connect a station, then register the collar it detects nearby.")


show()
