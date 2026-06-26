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
  <div class="mw-logo"><svg viewBox="0 0 100 100" width="40" height="40" fill="#1b1b2b" aria-hidden="true"><path d="M31.65 38.49C31.49 37.97 31.32 37.54 31.11 37.08C30.90 36.63 30.66 36.18 30.40 35.75C30.14 35.33 29.85 34.91 29.53 34.52C29.22 34.14 28.87 33.76 28.51 33.42C28.14 33.08 27.75 32.76 27.33 32.49C26.92 32.21 26.48 31.96 26.02 31.76C25.57 31.57 25.09 31.41 24.60 31.31C24.12 31.22 23.61 31.17 23.12 31.20C22.63 31.22 22.12 31.32 21.67 31.46C21.22 31.61 20.81 31.81 20.42 32.05C20.03 32.29 19.67 32.59 19.35 32.92C19.02 33.24 18.74 33.61 18.49 34.00C18.23 34.38 18.02 34.79 17.84 35.23C17.66 35.66 17.50 36.13 17.39 36.60C17.27 37.08 17.19 37.59 17.14 38.10C17.09 38.62 17.08 39.15 17.10 39.69C17.13 40.23 17.19 40.79 17.29 41.34C17.39 41.89 17.55 42.50 17.71 43.01C17.88 43.53 18.05 43.96 18.26 44.42C18.47 44.87 18.71 45.32 18.97 45.75C19.23 46.17 19.52 46.59 19.84 46.98C20.15 47.36 20.50 47.74 20.86 48.08C21.23 48.42 21.62 48.74 22.04 49.01C22.45 49.29 22.89 49.54 23.35 49.74C23.80 49.93 24.28 50.09 24.77 50.19C25.25 50.28 25.76 50.33 26.25 50.30C26.74 50.28 27.25 50.18 27.70 50.04C28.15 49.89 28.56 49.69 28.95 49.45C29.34 49.21 29.70 48.91 30.02 48.58C30.35 48.26 30.63 47.89 30.88 47.50C31.13 47.12 31.35 46.71 31.53 46.27C31.71 45.84 31.87 45.37 31.98 44.90C32.10 44.42 32.18 43.91 32.23 43.40C32.28 42.88 32.29 42.35 32.27 41.81C32.24 41.27 32.18 40.71 32.08 40.16C31.98 39.61 31.82 39.00 31.65 38.49Z"/><path d="M78.33 31.46C77.88 31.31 77.43 31.24 76.98 31.20C76.52 31.17 76.05 31.20 75.60 31.28C75.15 31.35 74.70 31.48 74.27 31.64C73.84 31.81 73.43 32.02 73.02 32.26C72.62 32.50 72.22 32.79 71.85 33.11C71.47 33.43 71.11 33.79 70.77 34.17C70.42 34.56 70.10 34.99 69.80 35.44C69.51 35.89 69.23 36.37 68.99 36.88C68.74 37.39 68.52 37.98 68.35 38.49C68.17 39.00 68.06 39.45 67.96 39.94C67.86 40.43 67.79 40.93 67.76 41.43C67.72 41.93 67.71 42.44 67.74 42.94C67.76 43.44 67.82 43.94 67.92 44.43C68.01 44.92 68.14 45.41 68.32 45.88C68.49 46.35 68.70 46.81 68.95 47.23C69.20 47.66 69.50 48.07 69.83 48.43C70.17 48.79 70.55 49.13 70.97 49.40C71.38 49.66 71.85 49.89 72.30 50.04C72.75 50.19 73.20 50.26 73.65 50.30C74.11 50.33 74.58 50.30 75.03 50.23C75.48 50.15 75.93 50.02 76.36 49.86C76.79 49.69 77.20 49.48 77.61 49.24C78.01 49.00 78.41 48.71 78.78 48.39C79.16 48.07 79.52 47.72 79.87 47.33C80.21 46.94 80.53 46.51 80.83 46.06C81.13 45.61 81.40 45.13 81.64 44.62C81.89 44.11 82.11 43.53 82.29 43.01C82.46 42.50 82.57 42.05 82.67 41.56C82.77 41.07 82.84 40.57 82.88 40.07C82.91 39.57 82.92 39.06 82.90 38.56C82.87 38.06 82.81 37.56 82.71 37.07C82.62 36.58 82.49 36.09 82.32 35.62C82.14 35.15 81.93 34.69 81.68 34.27C81.43 33.84 81.13 33.43 80.80 33.07C80.46 32.71 80.08 32.37 79.67 32.10C79.25 31.84 78.78 31.61 78.33 31.46Z"/><path d="M48.57 27.12C48.57 26.56 48.54 26.08 48.48 25.57C48.43 25.05 48.34 24.54 48.23 24.04C48.11 23.53 47.97 23.03 47.80 22.55C47.62 22.06 47.42 21.58 47.18 21.13C46.94 20.67 46.67 20.22 46.37 19.81C46.06 19.39 45.72 18.99 45.35 18.64C44.98 18.29 44.57 17.97 44.14 17.71C43.70 17.45 43.22 17.23 42.74 17.09C42.26 16.95 41.72 16.87 41.24 16.87C40.76 16.86 40.30 16.93 39.85 17.05C39.41 17.17 38.96 17.36 38.56 17.58C38.15 17.80 37.77 18.08 37.41 18.38C37.05 18.69 36.73 19.03 36.42 19.40C36.12 19.77 35.83 20.19 35.57 20.63C35.31 21.07 35.08 21.54 34.87 22.04C34.67 22.54 34.49 23.07 34.35 23.61C34.21 24.16 34.09 24.73 34.02 25.31C33.95 25.90 33.91 26.56 33.91 27.12C33.90 27.68 33.93 28.16 33.99 28.67C34.05 29.18 34.13 29.70 34.25 30.20C34.36 30.70 34.50 31.20 34.68 31.69C34.85 32.18 35.06 32.66 35.30 33.11C35.53 33.57 35.80 34.02 36.11 34.43C36.41 34.84 36.75 35.24 37.12 35.59C37.49 35.94 37.90 36.27 38.34 36.53C38.77 36.79 39.25 37.01 39.73 37.15C40.22 37.29 40.76 37.36 41.24 37.37C41.72 37.37 42.17 37.30 42.62 37.19C43.07 37.07 43.51 36.88 43.92 36.66C44.32 36.44 44.71 36.16 45.06 35.86C45.42 35.55 45.75 35.21 46.05 34.84C46.36 34.46 46.64 34.05 46.90 33.61C47.16 33.17 47.40 32.70 47.60 32.20C47.80 31.70 47.98 31.17 48.12 30.63C48.27 30.08 48.38 29.51 48.45 28.92C48.53 28.34 48.56 27.68 48.57 27.12Z"/><path d="M72.91 63.22C72.74 62.02 72.41 60.91 72.02 59.79C71.63 58.68 71.16 57.58 70.60 56.55C70.04 55.51 69.40 54.51 68.67 53.58C67.95 52.66 67.14 51.77 66.27 50.98C65.41 50.19 64.47 49.47 63.48 48.83C62.50 48.20 61.45 47.64 60.37 47.16C59.30 46.69 58.16 46.30 57.03 46.00C55.89 45.69 54.72 45.47 53.55 45.32C52.38 45.17 51.18 45.10 50.00 45.10C48.82 45.10 47.62 45.17 46.45 45.32C45.28 45.47 44.10 45.69 42.96 46.00C41.82 46.31 40.69 46.70 39.62 47.17C38.54 47.64 37.49 48.20 36.50 48.84C35.52 49.48 34.57 50.21 33.70 51.00C32.84 51.80 32.04 52.67 31.32 53.59C30.60 54.52 29.95 55.53 29.39 56.56C28.83 57.60 28.36 58.69 27.98 59.80C27.59 60.91 27.27 62.06 27.09 63.22C26.90 64.38 26.82 65.59 26.89 66.76C26.96 67.93 27.18 69.12 27.53 70.24C27.89 71.35 28.40 72.45 29.01 73.45C29.61 74.45 30.35 75.38 31.18 76.24C32.00 77.10 32.93 77.88 33.95 78.59C34.96 79.30 36.09 79.95 37.28 80.50C38.48 81.06 39.77 81.54 41.12 81.93C42.47 82.32 43.90 82.62 45.38 82.82C46.86 83.02 48.58 83.12 50.00 83.13C51.42 83.15 52.60 83.06 53.89 82.91C55.18 82.77 56.46 82.55 57.72 82.24C58.97 81.93 60.22 81.55 61.42 81.06C62.61 80.58 63.79 80.02 64.89 79.35C65.98 78.68 67.05 77.91 67.99 77.05C68.93 76.19 69.81 75.21 70.53 74.17C71.24 73.12 71.86 71.97 72.28 70.78C72.71 69.59 72.99 68.30 73.09 67.04C73.20 65.78 73.09 64.43 72.91 63.22Z"/><path d="M66.09 27.12C66.10 26.56 66.07 26.08 66.01 25.57C65.95 25.05 65.87 24.54 65.75 24.04C65.64 23.53 65.50 23.03 65.32 22.55C65.15 22.06 64.94 21.58 64.70 21.13C64.47 20.67 64.20 20.22 63.89 19.81C63.59 19.39 63.25 18.99 62.88 18.64C62.51 18.29 62.10 17.97 61.66 17.71C61.23 17.45 60.75 17.23 60.27 17.09C59.78 16.95 59.24 16.87 58.76 16.87C58.28 16.86 57.83 16.93 57.38 17.05C56.93 17.17 56.49 17.36 56.08 17.58C55.68 17.80 55.29 18.08 54.94 18.38C54.58 18.69 54.25 19.03 53.95 19.40C53.64 19.77 53.36 20.19 53.10 20.63C52.84 21.07 52.60 21.54 52.40 22.04C52.20 22.54 52.02 23.07 51.88 23.61C51.73 24.16 51.62 24.73 51.55 25.31C51.47 25.90 51.44 26.56 51.43 27.12C51.43 27.68 51.46 28.16 51.52 28.67C51.57 29.18 51.66 29.70 51.77 30.20C51.89 30.70 52.03 31.20 52.20 31.69C52.38 32.18 52.58 32.66 52.82 33.11C53.06 33.57 53.33 34.02 53.63 34.43C53.94 34.84 54.28 35.24 54.65 35.59C55.02 35.94 55.43 36.27 55.86 36.53C56.30 36.79 56.78 37.01 57.26 37.15C57.74 37.29 58.28 37.36 58.76 37.37C59.24 37.37 59.70 37.30 60.15 37.19C60.59 37.07 61.04 36.88 61.44 36.66C61.85 36.44 62.23 36.16 62.59 35.86C62.95 35.55 63.27 35.21 63.58 34.84C63.88 34.46 64.17 34.05 64.43 33.61C64.69 33.17 64.92 32.70 65.13 32.20C65.33 31.70 65.51 31.17 65.65 30.63C65.79 30.08 65.91 29.51 65.98 28.92C66.05 28.34 66.09 27.68 66.09 27.12Z"/></svg></div>
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

