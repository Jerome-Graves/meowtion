"""Simulated companion collar , "Purrminator".

Gives the demo/owner account a second, fully simulated collar with a realistic ~6-month activity
history that keeps growing, so the dashboard's collar switcher, history, Health watch and weather
context all have rich data to show.

  * Scheduled hourly: on the first run it backfills ~6 months of events (and the matching daily
    weather from Open-Meteo's free archive API); every run after, it appends new events up to "now"
    and refreshes the live state.
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


def _day_events(day, wx):
    """A realistic day for one cat as a list of (datetime_utc, activity, duration_minutes).

    `wx` is {"tempC":..., "raining":...} for that day, or None. Cats drink more when it's hot and
    stay in (less moving) when it's cold or wet, so the weather shows up in the data.
    """
    hot = bool(wx and (wx.get("tempC") or 15) >= 24)
    cold = bool(wx and (wx.get("tempC") or 15) <= 5)
    wet = bool(wx and wx.get("raining"))
    weekend = day.weekday() >= 5
    rng = random.Random(day.toordinal())   # stable per-day, but varied across days
    evs = []

    def add(hour, minute, activity, dur):
        evs.append((dt.datetime(day.year, day.month, day.day, hour, minute % 60,
                                tzinfo=dt.timezone.utc), activity, max(1, int(dur))))

    # night sleep
    add(0, 0, "sleep", 180 + rng.randint(-20, 40))
    add(3, rng.randint(0, 40), "sleep", 200 + rng.randint(-30, 60))
    # wake + breakfast
    add(7, rng.randint(0, 40), "eat", 6 + rng.randint(0, 6))
    add(7, 35, "drink", 1 + rng.randint(0, 2) + (2 if hot else 0))
    add(8, rng.randint(0, 30), "moving", 5 + rng.randint(0, 10))
    # morning
    add(9, 10, "resting", 60 + rng.randint(0, 70))
    if not wet:
        add(10, 30, "moving", 8 + rng.randint(0, 12))
    add(11, 30, "drink", 1 + rng.randint(0, 2) + (3 if hot else 0))
    # midday
    if rng.random() < 0.6:
        add(12, rng.randint(0, 30), "eat", 4 + rng.randint(0, 5))
    add(13, 10, "resting", 90 + rng.randint(0, 100))    # long afternoon nap
    # afternoon
    add(15, 30, "drink", 1 + rng.randint(0, 2) + (3 if hot else 0))
    if not cold and not wet:
        add(16, 10, "moving", 10 + rng.randint(0, 15))
    # evening: most active stretch + dinner
    add(17, 30, "play" if rng.random() < (0.6 if weekend else 0.4) else "moving", 12 + rng.randint(0, 18))
    add(18, rng.randint(0, 30), "eat", 8 + rng.randint(0, 7))
    add(18, 50, "drink", 2 + rng.randint(0, 3))
    if not wet:
        add(19, 30, "moving", 8 + rng.randint(0, 20))   # zoomies
    # settle for the night
    add(21, 10, "resting", 60 + rng.randint(0, 50))
    add(22, 40, "sleep", 80 + rng.randint(0, 50))
    return evs


def generate_events(start, now, weather):
    """All events with start in (start, now], across days. `weather` is {date_iso: {tempC,raining}}.
    Returns dicts {id, start, durationSec, type}, oldest first."""
    out, day = [], start.date()
    while day <= now.date():
        for when, activity, dur in _day_events(day, weather.get(day.isoformat())):
            if when <= start or when > now:
                continue
            ms = int(when.timestamp() * 1000)
            out.append({"id": str(ms), "start": ms, "durationSec": dur * 60, "type": activity})
        day += dt.timedelta(days=1)
    out.sort(key=lambda e: e["start"])
    return out


# --------------------------------------------------------------------------- #
# Firebase wiring
# --------------------------------------------------------------------------- #
def _owner_latlon(uid):
    loc = _ref(f"users/{uid}/profile/location").get() or {}
    if isinstance(loc, dict) and isinstance(loc.get("lat"), (int, float)):
        return loc["lat"], loc["lon"]
    return DEFAULT_LATLON


def _ensure_registered(base):
    _ref("/").update({
        f"{base}/{SIM_STATION}/type": "station",
        f"{base}/{SIM_STATION}/name": "Purrminator's pad (simulated)",
        f"{base}/{SIM_STATION}/simulated": True,
        f"{base}/{SIM_CAT}/type": "collar",
        f"{base}/{SIM_CAT}/name": SIM_NAME,
        f"{base}/{SIM_CAT}/simulated": True,
    })


def _last_event_ms(base):
    snap = _ref(f"{base}/{SIM_STATION}/cats/{SIM_CAT}/events").order_by_key().limit_to_last(1).get()
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
        updates[f"{base}/{SIM_STATION}/weather/history/{ts}"] = {
            "tempC": round(temp, 1) if temp is not None else None,
            "condition": cond, "raining": cond in ("rain", "thunder")}
    if updates:
        _ref("/").update(updates)
    print(f"simulate: wrote {len(updates)} days of weather")


def _weather_by_day(base):
    out = {}
    for ts, w in (_ref(f"{base}/{SIM_STATION}/weather/history").get() or {}).items():
        if not isinstance(w, dict):
            continue
        try:
            day = dt.datetime.fromtimestamp(int(ts) / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            continue
        out[day] = {"tempC": w.get("tempC"), "raining": bool(w.get("raining"))}
    return out


def _write_events(base, events):
    path = f"{base}/{SIM_STATION}/cats/{SIM_CAT}/events"
    items = [(f"{path}/{e['id']}",
              {"start": e["start"], "durationSec": e["durationSec"], "type": e["type"]})
             for e in events]
    for i in range(0, len(items), 500):          # batch so a backfill stays under update limits
        _ref("/").update(dict(items[i:i + 500]))


def _update_current(base, last):
    _ref(f"{base}/{SIM_STATION}/cats/{SIM_CAT}/current").set({
        "ts": int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000),
        "state": last["type"],
        "battery": random.randint(55, 95),
        "steps": random.randint(200, 2500),
    })


def run_simulation():
    """Backfill on the first run, else append new events up to now. Returns (count, mode)."""
    uid = _ref("config/demoOwner").get()
    if not uid:
        print("simulate: config/demoOwner not set; nothing to do")
        return 0, "skipped"
    base = f"users/{uid}/devices"
    _ensure_registered(base)

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

    events = generate_events(start, now, _weather_by_day(base))
    if events:
        _write_events(base, events)
        _update_current(base, events[-1])
    print(f"simulate: {mode}, wrote {len(events)} events for {SIM_NAME}")
    return len(events), mode


@scheduler_fn.on_schedule(schedule="every 1 hours", region=REGION,
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
