"""Read the owner's data from the Firebase Realtime Database.

Two reads, on purpose:
  * fetch()      , the WHOLE subtree (full activity history + device structure). This is the big one
                   (a 6-month history can be ~1 MB), so it's cached for a couple of minutes and must
                   NOT run on the live card's 10 s refresh.
  * fetch_live() , just the live bits: each cat's `current` state and its few most recent events,
                   read per cat so the 10 s refresh transfers a few KB instead of the whole history.
Both are shared across all viewers (including everyone on the public demo) via st.cache_data.
"""
import requests
import streamlit as st

_DEFAULT_DB = "https://meowtion-app-default-rtdb.europe-west1.firebasedatabase.app"


def _db_url():
    # Read lazily (not at import) so this never runs before st.set_page_config().
    try:
        return st.secrets["db_url"]
    except Exception:
        return _DEFAULT_DB


def _auth(token):
    # A real token reads only its owner; the demo account is world-readable (token=None).
    return {"auth": token} if token else {}


@st.cache_data(ttl=120)
def fetch(uid, token):
    """Return (status_code, data) for the user's whole subtree. `data` is None on error.
    Cached 2 min: this is the heavy read (full history + structure), so the live card doesn't use it
    on every refresh , it uses fetch_live() instead. New history events show up within the cache TTL.
    """
    r = requests.get(f"{_db_url()}/users/{uid}.json", params=_auth(token), timeout=10)
    return r.status_code, (r.json() if r.ok else None)


@st.cache_data(ttl=8)
def fetch_live(uid, token, cats):
    """The live bits only , each cat's `current` and its 8 most recent events , so the 10 s refresh
    is a few KB, not the whole history.

    `cats` is a tuple of (cat_id, path) pairs, where `path` is the cat node under the user
    (e.g. "devices/<collar>" for a standalone collar, or "devices/<station>/cats/<collar>" for one
    relayed by a station). It's a tuple so st.cache_data can hash it.

    Returns {cat_id: {"current": <dict|None>, "events": {id: event}}}.
    """
    base, out = _db_url(), {}
    for cat_id, path in cats:
        cur = requests.get(f"{base}/users/{uid}/{path}/current.json", params=_auth(token), timeout=10)
        # orderBy "$key" + limitToLast pulls only the most recent events (keys are start-ms strings,
        # so key order is time order). No index needed for "$key".
        ev = requests.get(f"{base}/users/{uid}/{path}/events.json",
                          params={**_auth(token), "orderBy": '"$key"', "limitToLast": 8}, timeout=10)
        out[cat_id] = {"current": cur.json() if cur.ok else None,
                       "events": (ev.json() if ev.ok else None) or {}}
    return out
