"""The live, auto-refreshing 'current state' cards for each cat (detected activity, steps,
battery, recent events). This is plumbing tied to the raw Firebase shape; the editable
analytics dashboard works off the clean DataFrame instead.
"""
import time

import streamlit as st

from .firebase import fetch
from .data import EVENT_ICON, fmt_time, fmt_dur, model_labels, iter_cats


def live_view(uid, token, only_cat=None):
    """Render the live cards. If `only_cat` (a cat's display name) is given, show just that one.
    Auto-refreshes every 10 s without rerunning the whole page."""

    @st.fragment(run_every=10)
    def _show():
        status, data = fetch(uid, token)
        if status == 401:
            st.error("Session expired , please sign in again.")
            return

        labels = model_labels(data)   # collar reports a class index; we map it to a name
        now_ms = time.time() * 1000
        found = False

        for rec in iter_cats(data):   # works for collars under a station OR standalone (simulated)
            cat_name = rec["name"]
            if only_cat and cat_name != only_cat:
                continue                         # collar switcher: show only the selected one
            found = True
            is_sim = rec["simulated"]
            cur = rec["current"] or {}
            ts = cur.get("ts")
            fresh = isinstance(ts, (int, float)) and (now_ms - ts) < 35000
            # ver == 2 = REAL on-device classification: cls indexes the model labels, conf is the
            # confidence. Otherwise it's a plain state label.
            real = cur.get("ver") == 2
            detected = None
            if real:
                cls = cur.get("cls")
                if isinstance(cls, int) and 0 <= cls < len(labels):
                    detected = labels[cls]

            st.subheader(f"🐈 {cat_name}")
            status = "🟢 online" if (is_sim or fresh) else "⚪ offline"   # a sim collar is always online
            via = "simulated" if is_sim else (f"via {rec['via']}" if rec["via"] else "")
            st.caption(status
                       + ("  ·  🧠 detecting on-device" if real else "")
                       + (f"  ·  {via}" if via else ""))

            c1, c2, c3 = st.columns(3)
            if real:
                conf = cur.get("conf")
                ic = EVENT_ICON.get(detected, "🧠")
                c1.metric("Detected", f"{ic} {detected}" if detected else "🧠 …",
                          delta=(f"{conf}%" if isinstance(conf, int) else None), delta_color="off")
            else:
                state = cur.get("state", "—")
                c1.metric("Activity" if is_sim else "State", f"{EVENT_ICON.get(state, '')} {state}".strip())
            c2.metric("Steps", cur.get("steps", "—"))
            batt = cur.get("battery")
            c3.metric("Battery", f"{batt}%" if batt is not None else "—")

            events = sorted(rec["events"].values(), key=lambda e: e.get("start", 0), reverse=True)
            if events:
                st.write("**Recent activity**")
                for e in events[:8]:
                    ecls = e.get("cls")
                    if e.get("ver") == 2 and isinstance(ecls, int) and 0 <= ecls < len(labels):
                        name = labels[ecls]
                    else:
                        name = e.get("type", "?")
                    ic = EVENT_ICON.get(name, "•")
                    st.write(f"{ic} {name}  ·  {fmt_time(e.get('start', 0))}  ·  {fmt_dur(e.get('durationSec', 0))}")

            weather = rec["weather"]
            if weather:
                rain = " · raining" if weather.get("raining") else ""
                st.caption(f"🌤 {weather.get('tempC', '?')}°C · {weather.get('condition', '?')}{rain}")
            st.divider()

        if not found:
            st.info("No cats yet. On the account page, connect a station, then register the collar it detects nearby.")

    _show()
