"""Read the owner's data from the Firebase Realtime Database. One cached read per 10 s,
shared across all viewers (including everyone on the public demo).
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


@st.cache_data(ttl=10)
def fetch(uid, token):
    """Return (status_code, data) for the user's whole subtree. `data` is None on error.
    A real token reads only its owner; the demo account is world-readable (token=None)."""
    params = {"auth": token} if token else {}
    r = requests.get(f"{_db_url()}/users/{uid}.json", params=params, timeout=10)
    return r.status_code, (r.json() if r.ok else None)
