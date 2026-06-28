"""Test fixtures for the Cloud Functions.

main.py imports the Firebase SDKs and calls initialize_app() at module load, which
needs cloud credentials we don't have under test. We stub those SDKs in sys.modules
before main is imported, so the pure NumPy DSP helpers can be unit-tested in isolation.
"""
import pathlib
import sys
import types

# --- stub firebase_functions (decorators + options used at import time) ---
_ff = types.ModuleType("firebase_functions")


class _MemoryOption:
    MB_256 = GB_4 = None


class _options:
    MemoryOption = _MemoryOption

    @staticmethod
    def CorsOptions(**_kwargs):
        return None


class _https_fn:
    @staticmethod
    def on_request(**_kwargs):
        def _decorator(fn):
            return fn
        return _decorator

    class Request:  # placeholders; the helper tests don't construct these
        pass

    class Response:
        def __init__(self, *_a, **_k):
            pass


_ff.https_fn = _https_fn
_ff.options = _options
sys.modules["firebase_functions"] = _ff

# --- stub firebase_admin (initialize_app + the names main.py imports) ---
_fa = types.ModuleType("firebase_admin")
_fa.initialize_app = lambda *_a, **_k: None
_fa.db = types.SimpleNamespace(reference=lambda *_a, **_k: None)
_fa.storage = types.SimpleNamespace(bucket=lambda *_a, **_k: None)
_fa.auth = types.SimpleNamespace(verify_id_token=lambda *_a, **_k: {})
sys.modules["firebase_admin"] = _fa

# main.py re-exports the scheduled simulator functions; stub the module so importing main
# doesn't drag in the scheduler decorators (irrelevant to the DSP helpers under test).
_sim = types.ModuleType("simulator")
_sim.simulate = lambda *_a, **_k: None
_sim.simulate_now = lambda *_a, **_k: None
sys.modules["simulator"] = _sim

# make functions/main.py importable as `main`
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
