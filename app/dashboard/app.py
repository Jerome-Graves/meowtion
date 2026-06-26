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
import pandas as pd
import altair as alt
import extra_streamlit_components as stx

st.set_page_config(page_title="Meowtion", page_icon="🐾")

# Brand the dashboard to match the static pages (css/base.css): Inter, the lavender radial-gradient
# canvas, and a proper brand block instead of the default title.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, .stApp, .stMarkdown, p, h1, h2, h3, label { font-family: 'Inter', system-ui, sans-serif; }
.stApp { background: radial-gradient(1100px 480px at 50% -220px, #e9e7fc, transparent), #f4f4f8; }
.mw-brand { display:flex; align-items:center; gap:.8rem; margin:.2rem 0 1.3rem; }
.mw-logo { width:46px; height:46px; border-radius:50%; display:grid; place-items:center;
  background:#bc7bc2; box-shadow:0 10px 30px rgba(16,18,40,.12); }
.mw-word { font-weight:800; font-size:1.5rem; letter-spacing:-.02em; line-height:1; color:#1b1b2b; }
.mw-tag { font-size:.82rem; color:#6b7280; margin-top:3px; }
</style>
<div class="mw-brand">
  <div class="mw-logo"><svg viewBox="0 0 100 100" width="100%" height="100%" fill="#1b1b2b" aria-hidden="true"><path d="M30.06 37.48C29.88 36.93 29.69 36.45 29.46 35.96C29.24 35.46 28.98 34.98 28.69 34.52C28.41 34.05 28.09 33.60 27.75 33.18C27.41 32.76 27.04 32.35 26.64 31.98C26.24 31.61 25.81 31.26 25.36 30.96C24.91 30.66 24.43 30.39 23.94 30.18C23.44 29.96 22.92 29.79 22.39 29.69C21.87 29.59 21.32 29.54 20.78 29.56C20.25 29.59 19.69 29.70 19.20 29.85C18.71 30.01 18.27 30.23 17.85 30.49C17.43 30.75 17.03 31.08 16.68 31.43C16.33 31.78 16.02 32.19 15.75 32.60C15.47 33.02 15.24 33.47 15.04 33.94C14.84 34.42 14.68 34.92 14.55 35.44C14.42 35.96 14.33 36.51 14.28 37.07C14.23 37.63 14.21 38.21 14.24 38.80C14.27 39.38 14.33 39.99 14.45 40.59C14.56 41.19 14.73 41.85 14.91 42.41C15.08 42.97 15.27 43.44 15.50 43.93C15.73 44.43 15.99 44.91 16.27 45.38C16.56 45.84 16.87 46.29 17.22 46.71C17.56 47.14 17.93 47.54 18.33 47.91C18.73 48.28 19.15 48.63 19.60 48.93C20.06 49.23 20.53 49.50 21.03 49.71C21.52 49.93 22.05 50.10 22.57 50.20C23.10 50.31 23.65 50.36 24.18 50.33C24.71 50.30 25.27 50.19 25.76 50.04C26.25 49.88 26.70 49.67 27.12 49.40C27.54 49.14 27.94 48.81 28.29 48.46C28.64 48.11 28.95 47.71 29.22 47.29C29.49 46.87 29.73 46.42 29.92 45.95C30.12 45.48 30.29 44.97 30.42 44.45C30.54 43.93 30.63 43.38 30.69 42.82C30.74 42.26 30.75 41.68 30.73 41.09C30.70 40.51 30.63 39.91 30.52 39.30C30.41 38.70 30.24 38.04 30.06 37.48Z"/><path d="M80.80 29.85C80.31 29.69 79.82 29.60 79.32 29.57C78.83 29.54 78.32 29.57 77.83 29.65C77.34 29.73 76.85 29.87 76.38 30.05C75.91 30.23 75.46 30.45 75.02 30.72C74.59 30.98 74.16 31.29 73.75 31.64C73.34 31.99 72.94 32.38 72.57 32.80C72.20 33.22 71.85 33.68 71.52 34.17C71.20 34.66 70.90 35.19 70.64 35.74C70.37 36.29 70.13 36.93 69.94 37.48C69.75 38.04 69.63 38.53 69.52 39.07C69.42 39.60 69.34 40.15 69.30 40.69C69.26 41.23 69.25 41.78 69.28 42.32C69.31 42.87 69.37 43.41 69.47 43.95C69.58 44.48 69.72 45.01 69.91 45.52C70.10 46.03 70.32 46.53 70.60 46.99C70.87 47.46 71.19 47.91 71.56 48.30C71.92 48.69 72.34 49.05 72.79 49.34C73.23 49.63 73.75 49.88 74.24 50.04C74.72 50.20 75.21 50.29 75.71 50.32C76.20 50.36 76.72 50.32 77.21 50.24C77.70 50.17 78.19 50.02 78.65 49.84C79.12 49.67 79.57 49.44 80.01 49.17C80.45 48.91 80.88 48.60 81.29 48.25C81.69 47.91 82.09 47.52 82.46 47.09C82.83 46.67 83.19 46.21 83.51 45.72C83.83 45.23 84.13 44.70 84.40 44.15C84.66 43.60 84.91 42.96 85.09 42.41C85.28 41.85 85.40 41.36 85.51 40.82C85.62 40.29 85.69 39.75 85.73 39.20C85.78 38.66 85.79 38.11 85.76 37.57C85.73 37.02 85.66 36.48 85.56 35.95C85.45 35.41 85.31 34.88 85.13 34.37C84.94 33.86 84.71 33.36 84.43 32.90C84.16 32.43 83.84 31.99 83.47 31.59C83.11 31.20 82.69 30.84 82.25 30.55C81.80 30.26 81.28 30.02 80.80 29.85Z"/><path d="M48.44 25.13C48.45 24.52 48.41 24.00 48.35 23.44C48.29 22.89 48.20 22.33 48.07 21.78C47.95 21.23 47.79 20.69 47.60 20.16C47.41 19.63 47.19 19.11 46.93 18.61C46.67 18.12 46.38 17.63 46.05 17.18C45.72 16.73 45.35 16.30 44.95 15.92C44.55 15.54 44.10 15.18 43.63 14.90C43.15 14.62 42.64 14.38 42.11 14.22C41.58 14.07 41.00 13.99 40.47 13.99C39.95 13.98 39.46 14.06 38.97 14.19C38.48 14.32 38.00 14.52 37.56 14.76C37.12 15.00 36.70 15.30 36.32 15.63C35.93 15.96 35.57 16.33 35.24 16.74C34.91 17.15 34.60 17.59 34.32 18.07C34.04 18.55 33.78 19.07 33.56 19.61C33.34 20.15 33.14 20.72 32.99 21.32C32.83 21.91 32.71 22.53 32.63 23.17C32.55 23.80 32.51 24.52 32.51 25.13C32.50 25.74 32.54 26.26 32.60 26.81C32.66 27.37 32.75 27.93 32.88 28.48C33.00 29.03 33.16 29.57 33.35 30.10C33.54 30.63 33.76 31.15 34.02 31.64C34.28 32.14 34.57 32.63 34.90 33.08C35.23 33.52 35.60 33.96 36.00 34.34C36.40 34.72 36.85 35.08 37.32 35.36C37.80 35.64 38.31 35.88 38.84 36.03C39.37 36.19 39.95 36.26 40.47 36.27C41.00 36.28 41.49 36.20 41.98 36.07C42.47 35.94 42.95 35.74 43.39 35.50C43.83 35.26 44.25 34.96 44.63 34.63C45.02 34.30 45.38 33.93 45.71 33.52C46.04 33.11 46.35 32.67 46.63 32.19C46.91 31.71 47.17 31.19 47.39 30.65C47.61 30.11 47.81 29.53 47.96 28.94C48.12 28.35 48.24 27.73 48.32 27.09C48.40 26.46 48.44 25.74 48.44 25.13Z"/><path d="M74.91 64.37C74.71 63.06 74.35 61.85 73.93 60.65C73.52 59.44 73.00 58.24 72.39 57.12C71.79 55.99 71.08 54.90 70.30 53.90C69.51 52.89 68.63 51.93 67.69 51.07C66.75 50.21 65.73 49.42 64.66 48.73C63.59 48.04 62.44 47.43 61.27 46.92C60.10 46.40 58.87 45.98 57.64 45.65C56.40 45.31 55.13 45.08 53.86 44.91C52.59 44.75 51.29 44.68 50.00 44.68C48.71 44.68 47.42 44.75 46.14 44.91C44.87 45.08 43.59 45.32 42.35 45.65C41.11 45.99 39.88 46.41 38.71 46.92C37.54 47.44 36.40 48.05 35.33 48.74C34.26 49.44 33.22 50.23 32.28 51.09C31.35 51.95 30.47 52.90 29.69 53.91C28.91 54.91 28.20 56.01 27.60 57.13C26.99 58.26 26.48 59.44 26.06 60.65C25.65 61.85 25.29 63.11 25.09 64.37C24.90 65.63 24.80 66.95 24.88 68.22C24.96 69.49 25.20 70.79 25.58 72.00C25.96 73.21 26.52 74.41 27.18 75.49C27.84 76.58 28.64 77.59 29.54 78.52C30.43 79.45 31.44 80.30 32.55 81.08C33.66 81.85 34.88 82.55 36.18 83.16C37.48 83.76 38.88 84.29 40.35 84.71C41.81 85.13 43.37 85.46 44.98 85.68C46.59 85.90 48.46 86.00 50.00 86.01C51.54 86.03 52.83 85.94 54.23 85.78C55.63 85.62 57.03 85.38 58.39 85.04C59.75 84.71 61.11 84.29 62.41 83.77C63.71 83.24 64.99 82.63 66.18 81.90C67.37 81.17 68.53 80.34 69.55 79.40C70.57 78.46 71.54 77.41 72.31 76.27C73.09 75.13 73.76 73.88 74.22 72.58C74.69 71.29 74.98 69.89 75.10 68.52C75.21 67.15 75.10 65.69 74.91 64.37Z"/><path d="M67.49 25.13C67.50 24.52 67.46 24.00 67.40 23.44C67.34 22.89 67.25 22.33 67.12 21.78C67.00 21.23 66.84 20.69 66.65 20.16C66.46 19.63 66.24 19.11 65.98 18.61C65.72 18.12 65.43 17.63 65.10 17.18C64.77 16.73 64.40 16.30 64.00 15.92C63.60 15.54 63.15 15.18 62.68 14.90C62.20 14.62 61.69 14.38 61.16 14.22C60.63 14.07 60.05 13.99 59.53 13.99C59.00 13.98 58.51 14.06 58.02 14.19C57.53 14.32 57.05 14.52 56.61 14.76C56.17 15.00 55.75 15.30 55.37 15.63C54.98 15.96 54.62 16.33 54.29 16.74C53.96 17.15 53.65 17.59 53.37 18.07C53.09 18.55 52.83 19.07 52.61 19.61C52.39 20.15 52.19 20.72 52.04 21.32C51.88 21.91 51.76 22.53 51.68 23.17C51.60 23.80 51.56 24.52 51.56 25.13C51.55 25.74 51.59 26.26 51.65 26.81C51.71 27.37 51.80 27.93 51.93 28.48C52.05 29.03 52.21 29.57 52.40 30.10C52.59 30.63 52.81 31.15 53.07 31.64C53.33 32.14 53.62 32.63 53.95 33.08C54.28 33.52 54.65 33.96 55.05 34.34C55.45 34.72 55.90 35.08 56.37 35.36C56.85 35.64 57.36 35.88 57.89 36.03C58.42 36.19 59.00 36.26 59.53 36.27C60.05 36.28 60.54 36.20 61.03 36.07C61.52 35.94 62.00 35.74 62.44 35.50C62.88 35.26 63.30 34.96 63.68 34.63C64.07 34.30 64.43 33.93 64.76 33.52C65.09 33.11 65.40 32.67 65.68 32.19C65.96 31.71 66.22 31.19 66.44 30.65C66.66 30.11 66.86 29.53 67.01 28.94C67.17 28.35 67.29 27.73 67.37 27.09C67.45 26.46 67.49 25.74 67.49 25.13Z"/></svg></div>
  <div>
    <div class="mw-word">Meowtion</div>
    <div class="mw-tag">On-device AI activity tracking · helping cats run the world, one nap at a time</div>
  </div>
</div>
""", unsafe_allow_html=True)


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


def activity_dataframe(data, model_labels):
    """Flatten every cat's logged episodes into one pandas DataFrame for charts.

    Columns deliberately match the beginner Streamlit tutorial so tutorial-style chart code
    works on the real data unchanged:
        activity | event_date | event_weekday_name | start_time | event_duration (minutes)
    `activity` is the trained model's label for real (ver==2) episodes, else the stored state name.
    """
    devices = (data or {}).get("devices", {})
    rows = []
    for station in devices.values():
        if not isinstance(station, dict):
            continue
        for cat_id, cat in (station.get("cats") or {}).items():
            cat_name = (devices.get(cat_id) or {}).get("name") or cat.get("name") or cat_id
            for ev in (cat.get("events") or {}).values():
                start = ev.get("start")
                if not isinstance(start, (int, float)):
                    continue
                dt = datetime.datetime.fromtimestamp(start / 1000)
                ecls = ev.get("cls")
                if ev.get("ver") == 2 and isinstance(ecls, int) and 0 <= ecls < len(model_labels):
                    activity = model_labels[ecls]          # real on-device class -> action name
                else:
                    activity = ev.get("type", "unknown")   # older / simulated episode
                rows.append({
                    "cat": cat_name,
                    "activity": str(activity).capitalize(),
                    "event_date": dt.strftime("%Y-%m-%d"),
                    "event_weekday_name": dt.strftime("%A"),
                    "start_time": dt.strftime("%H:%M"),
                    "event_duration": round((ev.get("durationSec") or 0) / 60.0, 2),  # minutes
                })
    return pd.DataFrame(rows, columns=["cat", "activity", "event_date",
                                       "event_weekday_name", "start_time", "event_duration"])


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
                    # Production episodes (ver==2) carry a class index; label them with the model's
                    # action name. Older/simulated episodes fall back to the state-name "type".
                    ecls = e.get("cls")
                    if e.get("ver") == 2 and isinstance(ecls, int) and 0 <= ecls < len(model_labels):
                        name = model_labels[ecls]
                    else:
                        name = e.get("type", "?")
                    ic = EVENT_ICON.get(name, "•")
                    st.write(f"{ic} {name}  ·  {fmt_time(e.get('start', 0))}  ·  {fmt_dur(e.get('durationSec', 0))}")

            if weather:
                rain = " · raining" if weather.get("raining") else ""
                st.caption(f"🌤 {weather.get('tempC', '?')}°C · {weather.get('condition', '?')}{rain}")
            st.divider()

    if not found:
        st.info("No cats yet. On the account page, connect a station, then register the collar it detects nearby.")


show()


# ============================================================================
# ACTIVITY HISTORY & CHARTS  ·  teammate-friendly playground (edit below!)
# ----------------------------------------------------------------------------
# `df` here is the cat's REAL logged activity as a pandas DataFrame, with the SAME
# column names as the beginner tutorial:
#     activity | event_date | event_weekday_name | start_time | event_duration (mins)
# So tutorial chart code works here unchanged - just use `df`. Add your own
# st.bar_chart / st.metric / altair charts in the marked area at the bottom.
# ============================================================================
_status, _data = fetch(uid, token)                 # cached - same call the live view above uses
_labels = (_data or {}).get("models", {}).get("labels") or []
df = activity_dataframe(_data, _labels)

st.divider()
st.subheader("📊 Activity history")
if df.empty:
    st.caption("Charts appear here once the collar has logged some episodes.")
    st.stop()

# --- from here `df` has data; everything below is plain tutorial-style code on `df` ---

# 😼 Theme flair: a cheeky "world domination" headline pulled from the real activity data.
_dom_h = round(df["event_duration"].sum() / 60)
_nap_h = round(df[df["activity"].str.lower() == "sleep"]["event_duration"].sum() / 60)
st.markdown(f"#### 😼 World-domination progress: **{_dom_h} h** logged "
            f"— _{_nap_h} h of it strategic napping._")

with st.expander("See the raw data table"):
    st.dataframe(df, use_container_width=True)

c1, c2, c3 = st.columns(3)
c1.metric("Episodes", len(df))
c2.metric("Minutes tracked", round(df["event_duration"].sum()))
c3.metric("Most common", df["activity"].value_counts().index[0])

# Charts render with a transparent background + no view box so they sit directly on the
# page's lavender gradient instead of in a clashing white panel. Bars use the brand lavender.
def _bars(data, x, y, y_title):
    return (
        alt.Chart(data)
        .mark_bar(color="#bc7bc2", cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=34)
        .encode(
            x=alt.X(f"{x}:N", title=None, sort="-y",
                    axis=alt.Axis(labelAngle=0, labelColor="#3a3a4a", labelFontWeight=600)),
            y=alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(labelColor="#6b7280", titleColor="#6b7280")),
            tooltip=[x, y],
        )
        .properties(height=260, background="transparent")
        .configure_view(fill=None, stroke=None)
        .configure_axis(grid=False, domainColor="#e6e7ec", tickColor="#e6e7ec")
    )

# Total minutes spent on each activity
by_activity = df.groupby("activity")["event_duration"].sum().reset_index()
st.write("**Total minutes per activity**")
st.altair_chart(_bars(by_activity, "activity", "event_duration", "minutes"), use_container_width=True)

# How many times each activity happened
counts = df["activity"].value_counts().reset_index()
counts.columns = ["activity", "count"]
st.write("**How often each activity happened**")
st.altair_chart(_bars(counts, "activity", "count", "episodes"), use_container_width=True)

# ============================================================================
# 👇 TEAMMATE: add your own charts here, using `df`. Same columns as your tutorial.
#    Example (copy + tweak):
#       st.bar_chart(df, x="event_weekday_name", y="event_duration", color="activity")
# ============================================================================

