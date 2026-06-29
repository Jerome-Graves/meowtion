"""The live, auto-refreshing 'current state' cards for each cat (detected activity, steps,
battery, recent events). This is plumbing tied to the raw Firebase shape; the editable
analytics dashboard works off the clean DataFrame instead.

Refresh strategy: the cat list, names, weather and labels come from the cached full read (fetch,
~2 min). The actually-live bits , each cat's current state and most recent events , come from a tiny
per-cat read (fetch_live, ~8 s), so this card stays near-real-time without re-downloading the whole
activity history every 10 seconds.
"""
import time

import streamlit as st

from .firebase import fetch, fetch_live
from .data import EVENT_ICON, fmt_time, fmt_dur, model_labels, iter_cats


def live_view(uid, token, only_cat=None, part="all"):
    """Render the live cards. If `only_cat` (a cat's display name) is given, show just that one.
    Auto-refreshes every 10 s without rerunning the whole page.

    `part` selects which half to render so the page can place them separately:
      "current" , the live current-state card (detected activity, steps, battery);
      "recent"  , the recent-events list;
      "all"     , both (default)."""

    @st.fragment(run_every=10)
    def _show():
        status, data = fetch(uid, token)          # cached structure + labels (heavy read, ~2 min)
        if status == 401:
            st.error("Session expired , please sign in again.")
            return

        labels = model_labels(data)   # collar reports a class index; we map it to a name
        cats = list(iter_cats(data))
        if not cats:
            st.info("No cats yet. On the account page, connect a station, then register the collar it detects nearby.")
            return
        shown = [r for r in cats if not only_cat or r["name"] == only_cat]   # collar switcher

        # fresh current + recent events, per cat , a few KB, refreshed every ~8 s
        live = fetch_live(uid, token, tuple((r["id"], r["path"]) for r in shown))
        now_ms = time.time() * 1000

        for rec in shown:
            lv = live.get(rec["id"]) or {}
            cur = lv.get("current") or rec["current"] or {}
            events = lv.get("events") or rec["events"] or {}

            cat_name = rec["name"]
            is_sim = rec["simulated"]
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

            # --- current-state card (detected activity, battery, weather) ---
            if part in ("all", "current"):
                st.subheader(f"🐈 {cat_name}")
                state_line = "🟢 online" if (is_sim or fresh) else "⚪ offline"   # a sim collar is always online
                via = "simulated" if is_sim else (f"via {rec['via']}" if rec["via"] else "")
                st.caption(state_line
                           + ("  ·  🧠 detecting on-device" if real else "")
                           + (f"  ·  {via}" if via else ""))

                c1, c2 = st.columns(2)
                if real and cur.get("cls") == 0xFE:        # 0xFE = low-power rest (rules-based gate)
                    c1.metric("Detected", f"{EVENT_ICON['rest']} Resting",
                              delta="low power", delta_color="off")
                elif real:
                    conf = cur.get("conf")
                    ic = EVENT_ICON.get(detected, "🧠")
                    c1.metric("Detected", f"{ic} {detected}" if detected else "🧠 …",
                              delta=(f"{conf}%" if isinstance(conf, int) else None), delta_color="off")
                else:
                    state = cur.get("state", "—")
                    c1.metric("Activity" if is_sim else "State", f"{EVENT_ICON.get(state, '')} {state}".strip())
                batt = cur.get("battery")
                c2.metric("Battery", f"{batt}%" if batt is not None else "—")

                weather = rec["weather"]
                if weather:
                    rain = " · raining" if weather.get("raining") else ""
                    st.caption(f"🌤 {weather.get('tempC', '?')}°C · {weather.get('condition', '?')}{rain}")

            # --- recent-events list ---
            if part in ("all", "recent"):
                recent = sorted(events.values(), key=lambda e: e.get("start", 0), reverse=True)
                if recent:
                    st.divider()
                    st.subheader("🐾 Recent activity")
                    for e in recent[:8]:
                        ecls = e.get("cls")
                        if e.get("ver") == 2 and isinstance(ecls, int) and 0 <= ecls < len(labels):
                            name = labels[ecls]
                        else:
                            name = e.get("type", "?")
                        ic = EVENT_ICON.get(name, "•")
                        st.write(f"{ic} {name}  ·  {fmt_time(e.get('start', 0))}  ·  {fmt_dur(e.get('durationSec', 0))}")
                    st.divider()

    _show()
