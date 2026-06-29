"""Page configuration and the Meowtion brand header. Keeps the (large) CSS + logo SVG out
of the entry file.
"""
import os

import streamlit as st

_DIR = os.path.dirname(os.path.abspath(__file__))
_FAVICON = os.path.join(_DIR, os.pardir, "static", "favicon.png")

# Brand the dashboard to match the static pages (css/base.css): Inter, the lavender radial
# gradient canvas, and a proper brand block (logo + wordmark) instead of the default title.
_BRAND_HTML = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, .stApp, .stMarkdown, p, h1, h2, h3, label { font-family: 'Inter', system-ui, sans-serif; }
.stApp { background: radial-gradient(1100px 480px at 50% -220px, #e9e7fc, transparent), #f4f4f8; }
/* Smoothly crossfade colours when the light/dark toggle flips. */
.stApp, .stApp *, .mw-word, .mw-tag {
  transition: background-color .30s ease, color .30s ease, border-color .30s ease,
              box-shadow .30s ease, fill .30s ease;
}
.mw-brand { display:flex; align-items:center; gap:.8rem; margin:.2rem 0 1.3rem; }
.mw-logo { width:46px; height:46px; border-radius:50%; display:grid; place-items:center;
  background:#bc7bc2; box-shadow:0 10px 30px rgba(16,18,40,.12); }
.mw-word { font-weight:800; font-size:2.1rem; letter-spacing:-.02em; line-height:1; color:#1b1b2b; }
.mw-tag { font-size:.82rem; color:#6b7280; margin-top:3px; }
/* Cat-selection segmented control. SELECTED = filled brand lavender, white text, with a leading check
   so it clearly stands out. UNSELECTED = muted grey that visibly recedes (dark mode overrides the
   unselected colours separately). */
button[data-testid="stBaseButton-segmented_controlActive"] { background:#bc7bc2 !important; border-color:#bc7bc2 !important; }
button[data-testid="stBaseButton-segmented_controlActive"], button[data-testid="stBaseButton-segmented_controlActive"] * { color:#ffffff !important; }
button[data-testid="stBaseButton-segmented_controlActive"]::before { content:"✓  "; font-weight:700; }
button[data-testid="stBaseButton-segmented_control"] { background:#ececf0 !important; border-color:#dcd6e4 !important; }
button[data-testid="stBaseButton-segmented_control"], button[data-testid="stBaseButton-segmented_control"] * { color:#8a8a96 !important; }
</style>
<div class="mw-brand">
  <div class="mw-logo"><svg viewBox="0 0 100 100" width="100%" height="100%" fill="#1b1b2b" aria-hidden="true"><path d="M30.06 37.48C29.88 36.93 29.69 36.45 29.46 35.96C29.24 35.46 28.98 34.98 28.69 34.52C28.41 34.05 28.09 33.60 27.75 33.18C27.41 32.76 27.04 32.35 26.64 31.98C26.24 31.61 25.81 31.26 25.36 30.96C24.91 30.66 24.43 30.39 23.94 30.18C23.44 29.96 22.92 29.79 22.39 29.69C21.87 29.59 21.32 29.54 20.78 29.56C20.25 29.59 19.69 29.70 19.20 29.85C18.71 30.01 18.27 30.23 17.85 30.49C17.43 30.75 17.03 31.08 16.68 31.43C16.33 31.78 16.02 32.19 15.75 32.60C15.47 33.02 15.24 33.47 15.04 33.94C14.84 34.42 14.68 34.92 14.55 35.44C14.42 35.96 14.33 36.51 14.28 37.07C14.23 37.63 14.21 38.21 14.24 38.80C14.27 39.38 14.33 39.99 14.45 40.59C14.56 41.19 14.73 41.85 14.91 42.41C15.08 42.97 15.27 43.44 15.50 43.93C15.73 44.43 15.99 44.91 16.27 45.38C16.56 45.84 16.87 46.29 17.22 46.71C17.56 47.14 17.93 47.54 18.33 47.91C18.73 48.28 19.15 48.63 19.60 48.93C20.06 49.23 20.53 49.50 21.03 49.71C21.52 49.93 22.05 50.10 22.57 50.20C23.10 50.31 23.65 50.36 24.18 50.33C24.71 50.30 25.27 50.19 25.76 50.04C26.25 49.88 26.70 49.67 27.12 49.40C27.54 49.14 27.94 48.81 28.29 48.46C28.64 48.11 28.95 47.71 29.22 47.29C29.49 46.87 29.73 46.42 29.92 45.95C30.12 45.48 30.29 44.97 30.42 44.45C30.54 43.93 30.63 43.38 30.69 42.82C30.74 42.26 30.75 41.68 30.73 41.09C30.70 40.51 30.63 39.91 30.52 39.30C30.41 38.70 30.24 38.04 30.06 37.48Z"/><path d="M80.80 29.85C80.31 29.69 79.82 29.60 79.32 29.57C78.83 29.54 78.32 29.57 77.83 29.65C77.34 29.73 76.85 29.87 76.38 30.05C75.91 30.23 75.46 30.45 75.02 30.72C74.59 30.98 74.16 31.29 73.75 31.64C73.34 31.99 72.94 32.38 72.57 32.80C72.20 33.22 71.85 33.68 71.52 34.17C71.20 34.66 70.90 35.19 70.64 35.74C70.37 36.29 70.13 36.93 69.94 37.48C69.75 38.04 69.63 38.53 69.52 39.07C69.42 39.60 69.34 40.15 69.30 40.69C69.26 41.23 69.25 41.78 69.28 42.32C69.31 42.87 69.37 43.41 69.47 43.95C69.58 44.48 69.72 45.01 69.91 45.52C70.10 46.03 70.32 46.53 70.60 46.99C70.87 47.46 71.19 47.91 71.56 48.30C71.92 48.69 72.34 49.05 72.79 49.34C73.23 49.63 73.75 49.88 74.24 50.04C74.72 50.20 75.21 50.29 75.71 50.32C76.20 50.36 76.72 50.32 77.21 50.24C77.70 50.17 78.19 50.02 78.65 49.84C79.12 49.67 79.57 49.44 80.01 49.17C80.45 48.91 80.88 48.60 81.29 48.25C81.69 47.91 82.09 47.52 82.46 47.09C82.83 46.67 83.19 46.21 83.51 45.72C83.83 45.23 84.13 44.70 84.40 44.15C84.66 43.60 84.91 42.96 85.09 42.41C85.28 41.85 85.40 41.36 85.51 40.82C85.62 40.29 85.69 39.75 85.73 39.20C85.78 38.66 85.79 38.11 85.76 37.57C85.73 37.02 85.66 36.48 85.56 35.95C85.45 35.41 85.31 34.88 85.13 34.37C84.94 33.86 84.71 33.36 84.43 32.90C84.16 32.43 83.84 31.99 83.47 31.59C83.11 31.20 82.69 30.84 82.25 30.55C81.80 30.26 81.28 30.02 80.80 29.85Z"/><path d="M48.44 25.13C48.45 24.52 48.41 24.00 48.35 23.44C48.29 22.89 48.20 22.33 48.07 21.78C47.95 21.23 47.79 20.69 47.60 20.16C47.41 19.63 47.19 19.11 46.93 18.61C46.67 18.12 46.38 17.63 46.05 17.18C45.72 16.73 45.35 16.30 44.95 15.92C44.55 15.54 44.10 15.18 43.63 14.90C43.15 14.62 42.64 14.38 42.11 14.22C41.58 14.07 41.00 13.99 40.47 13.99C39.95 13.98 39.46 14.06 38.97 14.19C38.48 14.32 38.00 14.52 37.56 14.76C37.12 15.00 36.70 15.30 36.32 15.63C35.93 15.96 35.57 16.33 35.24 16.74C34.91 17.15 34.60 17.59 34.32 18.07C34.04 18.55 33.78 19.07 33.56 19.61C33.34 20.15 33.14 20.72 32.99 21.32C32.83 21.91 32.71 22.53 32.63 23.17C32.55 23.80 32.51 24.52 32.51 25.13C32.50 25.74 32.54 26.26 32.60 26.81C32.66 27.37 32.75 27.93 32.88 28.48C33.00 29.03 33.16 29.57 33.35 30.10C33.54 30.63 33.76 31.15 34.02 31.64C34.28 32.14 34.57 32.63 34.90 33.08C35.23 33.52 35.60 33.96 36.00 34.34C36.40 34.72 36.85 35.08 37.32 35.36C37.80 35.64 38.31 35.88 38.84 36.03C39.37 36.19 39.95 36.26 40.47 36.27C41.00 36.28 41.49 36.20 41.98 36.07C42.47 35.94 42.95 35.74 43.39 35.50C43.83 35.26 44.25 34.96 44.63 34.63C45.02 34.30 45.38 33.93 45.71 33.52C46.04 33.11 46.35 32.67 46.63 32.19C46.91 31.71 47.17 31.19 47.39 30.65C47.61 30.11 47.81 29.53 47.96 28.94C48.12 28.35 48.24 27.73 48.32 27.09C48.40 26.46 48.44 25.74 48.44 25.13Z"/><path d="M74.91 64.37C74.71 63.06 74.35 61.85 73.93 60.65C73.52 59.44 73.00 58.24 72.39 57.12C71.79 55.99 71.08 54.90 70.30 53.90C69.51 52.89 68.63 51.93 67.69 51.07C66.75 50.21 65.73 49.42 64.66 48.73C63.59 48.04 62.44 47.43 61.27 46.92C60.10 46.40 58.87 45.98 57.64 45.65C56.40 45.31 55.13 45.08 53.86 44.91C52.59 44.75 51.29 44.68 50.00 44.68C48.71 44.68 47.42 44.75 46.14 44.91C44.87 45.08 43.59 45.32 42.35 45.65C41.11 45.99 39.88 46.41 38.71 46.92C37.54 47.44 36.40 48.05 35.33 48.74C34.26 49.44 33.22 50.23 32.28 51.09C31.35 51.95 30.47 52.90 29.69 53.91C28.91 54.91 28.20 56.01 27.60 57.13C26.99 58.26 26.48 59.44 26.06 60.65C25.65 61.85 25.29 63.11 25.09 64.37C24.90 65.63 24.80 66.95 24.88 68.22C24.96 69.49 25.20 70.79 25.58 72.00C25.96 73.21 26.52 74.41 27.18 75.49C27.84 76.58 28.64 77.59 29.54 78.52C30.43 79.45 31.44 80.30 32.55 81.08C33.66 81.85 34.88 82.55 36.18 83.16C37.48 83.76 38.88 84.29 40.35 84.71C41.81 85.13 43.37 85.46 44.98 85.68C46.59 85.90 48.46 86.00 50.00 86.01C51.54 86.03 52.83 85.94 54.23 85.78C55.63 85.62 57.03 85.38 58.39 85.04C59.75 84.71 61.11 84.29 62.41 83.77C63.71 83.24 64.99 82.63 66.18 81.90C67.37 81.17 68.53 80.34 69.55 79.40C70.57 78.46 71.54 77.41 72.31 76.27C73.09 75.13 73.76 73.88 74.22 72.58C74.69 71.29 74.98 69.89 75.10 68.52C75.21 67.15 75.10 65.69 74.91 64.37Z"/><path d="M67.49 25.13C67.50 24.52 67.46 24.00 67.40 23.44C67.34 22.89 67.25 22.33 67.12 21.78C67.00 21.23 66.84 20.69 66.65 20.16C66.46 19.63 66.24 19.11 65.98 18.61C65.72 18.12 65.43 17.63 65.10 17.18C64.77 16.73 64.40 16.30 64.00 15.92C63.60 15.54 63.15 15.18 62.68 14.90C62.20 14.62 61.69 14.38 61.16 14.22C60.63 14.07 60.05 13.99 59.53 13.99C59.00 13.98 58.51 14.06 58.02 14.19C57.53 14.32 57.05 14.52 56.61 14.76C56.17 15.00 55.75 15.30 55.37 15.63C54.98 15.96 54.62 16.33 54.29 16.74C53.96 17.15 53.65 17.59 53.37 18.07C53.09 18.55 52.83 19.07 52.61 19.61C52.39 20.15 52.19 20.72 52.04 21.32C51.88 21.91 51.76 22.53 51.68 23.17C51.60 23.80 51.56 24.52 51.56 25.13C51.55 25.74 51.59 26.26 51.65 26.81C51.71 27.37 51.80 27.93 51.93 28.48C52.05 29.03 52.21 29.57 52.40 30.10C52.59 30.63 52.81 31.15 53.07 31.64C53.33 32.14 53.62 32.63 53.95 33.08C54.28 33.52 54.65 33.96 55.05 34.34C55.45 34.72 55.90 35.08 56.37 35.36C56.85 35.64 57.36 35.88 57.89 36.03C58.42 36.19 59.00 36.26 59.53 36.27C60.05 36.28 60.54 36.20 61.03 36.07C61.52 35.94 62.00 35.74 62.44 35.50C62.88 35.26 63.30 34.96 63.68 34.63C64.07 34.30 64.43 33.93 64.76 33.52C65.09 33.11 65.40 32.67 65.68 32.19C65.96 31.71 66.22 31.19 66.44 30.65C66.66 30.11 66.86 29.53 67.01 28.94C67.17 28.35 67.29 27.73 67.37 27.09C67.45 26.46 67.49 25.74 67.49 25.13Z"/></svg></div>
  <div>
    <div class="mw-word">Meowtion</div>
    <div class="mw-tag">On-device AI activity tracking · helping cats run the world, one nap at a time</div>
  </div>
</div>
"""


def is_dark():
    """True if the viewer turned on dark mode with the in-page toggle (stored in session state and
    mirrored to the URL so it survives a reload). Defaults to light. Our custom CSS and the charts
    read this so they adapt together."""
    return bool(st.session_state.get("mw_dark_toggle", False))


# Dark-mode overrides. The base CSS (in _BRAND_HTML) is light; when the toggle is on we layer this on
# top (later CSS wins). Streamlit's own widgets follow its config theme, not our toggle, so we have to
# recolour text, metrics, buttons, expanders and surfaces here as well as the brand bar.
_DARK_CSS = """
<style>
.stApp { background: radial-gradient(1100px 480px at 50% -220px, #2b2750, transparent), #0e0e15; }
.mw-word { color:#ececf2; }
.mw-tag, [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color:#9aa0ad !important; }
.stApp, .stApp p, .stApp li,
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stHeading"], h1, h2, h3, h4, h5,
[data-testid="stWidgetLabel"] label, [data-testid="stWidgetLabel"] p { color:#e7e7ef; }
[data-testid="stMetricValue"], [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * { color:#e7e7ef !important; }
[data-testid="stMetricDelta"] { color:#b8b8c4 !important; }
.st-key-reset_timeline_zoom button { background:#22222e !important; border:1px solid #3a3a48 !important; }
.st-key-reset_timeline_zoom button, .st-key-reset_timeline_zoom button * { color:#e7e7ef !important; }
[data-testid="stExpander"] details { background:#15151d; border:1px solid #2a2a36; border-radius:.5rem; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color:#e7e7ef; }
/* segmented control (Cat Selection) in dark mode: muted dark unselected segments (the selected one is
   the lavender fill from the base CSS). */
button[data-testid="stBaseButton-segmented_control"] { background:#26262f !important; border-color:#3a3a48 !important; }
button[data-testid="stBaseButton-segmented_control"], button[data-testid="stBaseButton-segmented_control"] * { color:#8f8f9b !important; }
hr { border-color:#2a2a36 !important; }
a { color:#d6a9db; }
/* date-picker calendar popup (baseweb, rendered at document level). Paint the whole popup solid dark
   with light text first (kills the white header strip and empty-cell blocks), then colour only the
   states that mean something: selected day = lavender, in-range days = lavender tint, disabled =
   dimmed. */
div[data-baseweb="popover"]:has([data-baseweb="calendar"]) > div { background-color:#1d1d27 !important; }
[data-baseweb="calendar"], [data-baseweb="calendar"] * { background-color:#1d1d27 !important; color:#e7e7ef !important; }
/* remove baseweb's today/focus rings (the stray lavender outline around a day) */
[data-baseweb="calendar"] *,
[data-baseweb="calendar"] *::before,
[data-baseweb="calendar"] *::after { box-shadow:none !important; border-color:transparent !important; outline:none !important; }
/* selected day = filled lavender, white text (match by aria-selected AND by aria-label, since
   baseweb labels the chosen day "...it's selected"); fill the centre so it matches the ring. */
[data-baseweb="calendar"] [aria-selected="true"], [data-baseweb="calendar"] [aria-selected="true"] *,
[data-baseweb="calendar"] [aria-label*="selected" i], [data-baseweb="calendar"] [aria-label*="selected" i] * { background-color:#bc7bc2 !important; color:#ffffff !important; border-radius:50% !important; }
/* unselectable days = clearly dimmer than the selectable (bright) ones. baseweb may use aria-disabled
   OR the disabled attribute OR an aria-label of "not available", so cover all. */
[data-baseweb="calendar"] [aria-disabled="true"], [data-baseweb="calendar"] [aria-disabled="true"] *,
[data-baseweb="calendar"] [disabled], [data-baseweb="calendar"] [disabled] *,
[data-baseweb="calendar"] [aria-label*="not available" i], [data-baseweb="calendar"] [aria-label*="not available" i] *,
[data-baseweb="calendar"] [aria-label*="unavailable" i], [data-baseweb="calendar"] [aria-label*="unavailable" i] * { color:#44444e !important; }
/* hover on a selectable day: baseweb uses a light hover background (light-on-light in dark mode), so
   keep it a dark lavender tint with light text. Covers the cell, its children and baseweb's pseudo
   highlight. Leaves the selected and unavailable days alone. */
[data-baseweb="calendar"] [role="gridcell"]:hover:not([aria-label*="selected" i]):not([aria-label*="not available" i]),
[data-baseweb="calendar"] [role="gridcell"]:hover:not([aria-label*="selected" i]):not([aria-label*="not available" i]) *,
[data-baseweb="calendar"] [role="gridcell"]:hover:not([aria-label*="selected" i]):not([aria-label*="not available" i])::before,
[data-baseweb="calendar"] [role="gridcell"]:hover:not([aria-label*="selected" i]):not([aria-label*="not available" i])::after { background-color:#33293f !important; color:#ffffff !important; }
/* hover on an unselected cat segment: keep it dark instead of baseweb's light hover */
button[data-testid="stBaseButton-segmented_control"]:hover { background-color:#33333d !important; }
button[data-testid="stBaseButton-segmented_control"]:hover, button[data-testid="stBaseButton-segmented_control"]:hover * { color:#e7e7ef !important; }
</style>
"""


def configure_page():
    """Set the page title and icon. Must be the FIRST Streamlit call in the app."""
    st.set_page_config(page_title="Meowtion",
                       page_icon=_FAVICON if os.path.exists(_FAVICON) else "🐾")


def brand_header():
    """Render the Meowtion brand bar and apply the page theme CSS. Light by default; if the in-page
    toggle is on, the dark overrides are appended to the SAME markdown call. (Rendering them as a
    second st.markdown would add an empty element container, nudging the whole page down a few px when
    dark is on, so dividers appeared to shift between themes.)"""
    st.markdown(_BRAND_HTML + (_DARK_CSS if is_dark() else ""), unsafe_allow_html=True)
