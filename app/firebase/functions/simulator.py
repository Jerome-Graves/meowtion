"""Simulated companion collar , "Purrminator".

Gives the demo/owner account a second, fully simulated collar (a STANDALONE device , no station)
with a realistic ~6-month activity history that keeps growing, so the dashboard's collar switcher,
history, Health watch and weather context all have rich data to show.

  * Scheduled every 15 minutes: on the first run it backfills ~6 months of events (and the matching
    daily weather from Open-Meteo's free archive API); every run after, it appends new events up to
    "now" from a continuous time-of-day timeline, and refreshes the live state.
  * simulate_now (HTTP, dev-account token): kick a run immediately instead of waiting for the timer.

Everything is generated; it never touches the real collar. Idempotent: events are keyed by their
start time, so re-running can't duplicate them. Name/account are constants below.

Deploy with the other functions:  firebase deploy --only functions   (from app/firebase/)
"""
import datetime as dt
import json
import random
import urllib.request

from firebase_functions import scheduler_fn, https_fn, options
from firebase_admin import db, auth

DB_URL = "https://meowtion-app-default-rtdb.europe-west1.firebasedatabase.app"
REGION = "europe-west1"

SIM_NAME = "Purrminator"                   # the collar's pun name (change here)
SIM_STATION = "sim-station-purrminator"    # fixed station device id for the sim
SIM_CAT = "cat-purrminator"                # fixed collar/cat id
BACKFILL_DAYS = 182                        # ~6 months
GEN_VERSION = 2                            # bump to force a clean rebuild when the model changes
DEFAULT_LATLON = (51.5074, -0.1278)        # London, used only if the owner has no stored location


def _ref(path):
    return db.reference(path, url=DB_URL)


# --------------------------------------------------------------------------- #
# Pure generation (no Firebase) , easy to reason about and test.
# --------------------------------------------------------------------------- #
def _condition(code, precip):
    """Open-Meteo WMO code (+ precip) -> the coarse labels the firmware uses."""
    if code >= 95: return "thunder"
    if 71 <= code <= 77: return "snow"
    if (51 <= code <= 67) or (80 <= code <= 82) or precip > 0: return "rain"
    if 1 <= code <= 3: return "cloudy"
    if code in (45, 48): return "fog"
    return "clear"


# Typical duration range in SECONDS per activity. A cat laps water for under a minute, eats for a
# couple of minutes, plays/moves for several, naps for ~an hour, and sleeps for hours.
_DUR = {
    "sleep":   (5400, 14400),   # 1.5 , 4 h
    "resting": (1800, 7200),    # 30 , 120 min
    "moving":  (120, 900),      # 2 , 15 min
    "play":    (180, 1200),     # 3 , 20 min
    "eat":     (60, 300),       # 1 , 5 min
    "drink":   (15, 75),        # 15 , 75 s
}


def _hour_weights(h):
    """How likely the cat is to START each activity in hour `h` (0-23). The cat does a continuous
    chain of activities; these weights bias what comes next by time of day."""
    if h < 6:    return {"sleep": 10, "resting": 2}                                  # deep night
    if h == 6:   return {"sleep": 4, "resting": 3, "eat": 2, "drink": 1, "moving": 1}  # waking
    if h <= 8:   return {"eat": 3, "drink": 2, "moving": 3, "resting": 3}            # breakfast
    if h <= 11:  return {"resting": 6, "moving": 2, "drink": 1, "eat": 1}            # morning naps
    if h <= 13:  return {"resting": 4, "eat": 2, "drink": 1, "moving": 1}            # midday
    if h <= 16:  return {"resting": 7, "moving": 2, "drink": 1}                      # afternoon
    if h <= 20:  return {"play": 3, "moving": 4, "eat": 2, "drink": 2, "resting": 3}  # active evening
    if h <= 22:  return {"resting": 5, "moving": 1, "drink": 1}                      # settling
    return {"sleep": 6, "resting": 2}                                               # late night


def _day_timeline(day, wx):
    """A continuous chain of activities filling one day, as (start_ms, activity, duration_sec).
    Deterministic for a given date (seeded by the date), so re-running can never duplicate events.
    Weather nudges it: hotter -> more/longer drinking; cold or wet -> shorter moving/play."""
    hot = bool(wx and (wx.get("tempC") or 15) >= 24)
    coldwet = bool(wx and ((wx.get("tempC") or 15) <= 5 or wx.get("raining")))
    rng = random.Random(day.toordinal())
    t = dt.datetime(day.year, day.month, day.day, 0, 0, tzinfo=dt.timezone.utc)
    day_end = t + dt.timedelta(days=1)
    out = []
    while t < day_end:
        w = dict(_hour_weights(t.hour))
        if hot:
            w["drink"] = w.get("drink", 0) + 3
        act = rng.choices(list(w), weights=list(w.values()), k=1)[0]
        lo, hi = _DUR[act]
        dur = rng.randint(lo, hi)                 # seconds
        if act == "drink" and hot:
            dur += rng.randint(10, 40)            # a bit longer at the bowl when it's hot
        if act in ("moving", "play") and coldwet:
            dur = max(60, dur // 2)
        out.append((int(t.timestamp() * 1000), act, dur))
        t += dt.timedelta(seconds=dur)
    return out


def generate_events(start, now, weather):
    """All events that START in (start, now], built from each day's continuous timeline.
    `weather` is {date_iso: {tempC, raining}}. Returns {id, start, durationSec, type}, oldest first."""
    out, day = [], start.date()
    while day <= now.date():
        for ms, act, dursec in _day_timeline(day, weather.get(day.isoformat())):
            when = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)
            if when <= start or when > now:
                continue
            out.append({"id": str(ms), "start": ms, "durationSec": dursec, "type": act})
        day += dt.timedelta(days=1)
    out.sort(key=lambda e: e["start"])
    return out


def current_activity(now, weather):
    """What the cat is doing right now , the timeline activity whose span covers `now`."""
    nowms = int(now.timestamp() * 1000)
    for ms, act, dursec in _day_timeline(now.date(), weather.get(now.date().isoformat())):
        if ms <= nowms < ms + dursec * 1000:
            return act
    return "resting"


# --------------------------------------------------------------------------- #
# Firebase wiring
# --------------------------------------------------------------------------- #
def _owner_latlon(uid):
    loc = _ref(f"users/{uid}/profile/location").get() or {}
    if isinstance(loc, dict) and isinstance(loc.get("lat"), (int, float)):
        return loc["lat"], loc["lon"]
    return DEFAULT_LATLON


def _ensure_registered(base):
    # The simulated collar is a STANDALONE device , no station; its data lives directly on it.
    _ref("/").update({
        f"{base}/{SIM_CAT}/type": "collar",
        f"{base}/{SIM_CAT}/name": SIM_NAME,
        f"{base}/{SIM_CAT}/simulated": True,
    })
    if _ref(f"{base}/{SIM_STATION}").get():        # drop the old station-based layout, if present
        _ref(f"{base}/{SIM_STATION}").delete()


def _last_event_ms(base):
    snap = _ref(f"{base}/{SIM_CAT}/events").order_by_key().limit_to_last(1).get()
    if not snap:
        return None
    try:
        return int(next(iter(snap)))
    except (ValueError, StopIteration):
        return None


def _backfill_weather(base, lat, lon, start, end):
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={lat:.3f}&longitude={lon:.3f}"
           f"&start_date={start.date()}&end_date={end.date()}"
           f"&daily=temperature_2m_mean,precipitation_sum,weather_code&timezone=UTC")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            j = json.load(r)
    except Exception as ex:   # noqa: BLE001 , weather is best-effort context
        print("simulate: weather archive failed:", ex)
        return
    d = j.get("daily", {})
    days, temps = d.get("time", []), d.get("temperature_2m_mean", [])
    precs, codes = d.get("precipitation_sum", []), d.get("weather_code", [])
    updates = {}
    for i, day in enumerate(days):
        temp = temps[i] if i < len(temps) else None
        prec = (precs[i] if i < len(precs) else 0) or 0
        cond = _condition(codes[i] if i < len(codes) else 0, prec)
        ts = int(dt.datetime.fromisoformat(day).replace(hour=12, tzinfo=dt.timezone.utc).timestamp() * 1000)
        updates[f"{base}/{SIM_CAT}/weather/history/{ts}"] = {
            "tempC": round(temp, 1) if temp is not None else None,
            "condition": cond, "raining": cond in ("rain", "thunder")}
    if updates:
        _ref("/").update(updates)
    print(f"simulate: wrote {len(updates)} days of weather")


def _weather_by_day(base):
    out = {}
    for ts, w in (_ref(f"{base}/{SIM_CAT}/weather/history").get() or {}).items():
        if not isinstance(w, dict):
            continue
        try:
            day = dt.datetime.fromtimestamp(int(ts) / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            continue
        out[day] = {"tempC": w.get("tempC"), "raining": bool(w.get("raining"))}
    return out


def _write_events(base, events):
    path = f"{base}/{SIM_CAT}/events"
    items = [(f"{path}/{e['id']}",
              {"start": e["start"], "durationSec": e["durationSec"], "type": e["type"]})
             for e in events]
    for i in range(0, len(items), 500):          # batch so a backfill stays under update limits
        _ref("/").update(dict(items[i:i + 500]))


def _update_current(base, activity):
    """Set the live state to what the cat is doing now, with a fresh timestamp."""
    _ref(f"{base}/{SIM_CAT}/current").set({
        "ts": int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000),
        "state": activity,
        "battery": random.randint(55, 95),
        "steps": random.randint(200, 2500),
    })


def run_simulation():
    """Backfill on the first run, else append new events up to now; always refresh the live state
    to the cat's current time-of-day activity. Returns (count, mode)."""
    uid = _ref("config/demoOwner").get()
    if not uid:
        print("simulate: config/demoOwner not set; nothing to do")
        return 0, "skipped"
    base = f"users/{uid}/devices"
    _ensure_registered(base)

    # If the generation model changed, wipe the old events so they're rebuilt cleanly (a re-run
    # with different durations would otherwise leave stale events behind).
    if _ref(f"{base}/{SIM_CAT}/genVersion").get() != GEN_VERSION:
        _ref(f"{base}/{SIM_CAT}/events").delete()
        _ref(f"{base}/{SIM_CAT}/genVersion").set(GEN_VERSION)

    now = dt.datetime.now(dt.timezone.utc)
    last = _last_event_ms(base)
    if last is None:
        start = now - dt.timedelta(days=BACKFILL_DAYS)
        lat, lon = _owner_latlon(uid)
        _backfill_weather(base, lat, lon, start, now)
        mode = "backfill"
    else:
        start = dt.datetime.fromtimestamp(last / 1000, tz=dt.timezone.utc) + dt.timedelta(seconds=1)
        mode = "top-up"

    weather = _weather_by_day(base)
    events = generate_events(start, now, weather)
    if events:
        _write_events(base, events)
    _update_current(base, current_activity(now, weather))   # live state always reflects "now"
    print(f"simulate: {mode}, wrote {len(events)} events for {SIM_NAME}")
    return len(events), mode


@scheduler_fn.on_schedule(schedule="every 15 minutes", region=REGION,
                          memory=options.MemoryOption.MB_256, timeout_sec=300)
def simulate(event: scheduler_fn.ScheduledEvent) -> None:
    run_simulation()


@https_fn.on_request(region=REGION, memory=options.MemoryOption.MB_256, timeout_sec=300)
def simulate_now(req: https_fn.Request) -> https_fn.Response:
    """Manually trigger a run (so you don't wait for the hourly timer). Requires a dev-account token."""
    token = (req.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    try:
        uid = auth.verify_id_token(token)["uid"]
    except Exception:   # noqa: BLE001
        return https_fn.Response("unauthorized", status=401)
    if _ref(f"config/devAccounts/{uid}").get() is not True:
        return https_fn.Response("not a dev account", status=403)
    count, mode = run_simulation()
    return https_fn.Response(json.dumps({"mode": mode, "events": count}), status=200,
                             headers={"Content-Type": "application/json"})
