# Dashboard (Streamlit)

The owner-facing web app. One Streamlit deployment serves three **same-origin** pages:

| Page | File | Language | What it does |
|------|------|----------|--------------|
| Front door | [`static/account.html`](static/account.html) | JS | Log in / sign up / demo, manage account (incl. delete), register devices over Web Serial |
| Dashboard | [`app.py`](app.py) | Python | The live view of the signed-in owner's cats and stations |
| Dev console | [`static/dev.html`](static/dev.html) | JS | Dev-account only: capture training clips, label/trim them, define actions, trigger cloud training |

## Why a static front door

Device registration needs the **Web Serial API** (browser JavaScript), which can't run in
Streamlit's Python or its sandboxed component iframes. So the front door and dev console are
static JS pages, served from the **same origin** by Streamlit's static serving
(`enableStaticServing`, see `.streamlit/config.toml`).

## Login & session

You log in once on the front door (`account.html`) with Firebase Auth (email/password or Google).
It writes the Firebase ID token into a same-origin cookie (`mtoken`).

`app.py` reads that cookie with the **`extra-streamlit-components` `CookieManager`** (client-side),
*not* `st.context.cookies` , Streamlit Community Cloud does not expose browser cookies to the
server, so the server-side API is always empty there. Logged-out visitors get a **sign-in gate**
(the dashboard is never shown); **Log out** navigates to `account.html?logout=1`, which signs out
of Firebase, clears the cookie, and returns to the login form. No token is ever put in the URL.

Trust comes from the **database rules**: a real token reads only its owner; the demo account is
world-readable but write-locked, so the demo is genuinely read-only.

## Python code layout

`app.py` is a thin entry point , it only wires the pieces in order (theme → sign-in → live cards →
analytics). Everything else is split so you can work on the charts without reading any login or
data-formatting code:

```
app/dashboard/
├── app.py              entry point (wiring only)
├── dashboard_view.py   the editable analytics view  ←  TEAMMATES EDIT THIS
└── meowtion_dash/      plumbing (rarely opened)
    ├── theme.py        page config + brand header
    ├── auth.py         cookie / JWT sign-in → (uid, token, is_demo)
    ├── firebase.py     cached Realtime Database read
    ├── data.py         activity_dataframe() + filter helpers
    ├── charts.py       branded Altair chart helper
    └── live.py         live current-state cards
```

**Teammates:** edit [`dashboard_view.py`](dashboard_view.py). You are handed a clean pandas
DataFrame `df` (one row per episode: `cat, activity, event_date, event_weekday_name, start_time,
event_duration`) plus ready-made helpers from `meowtion_dash` (filters and a branded chart). You
never touch cookies, JWTs, or the raw Firebase JSON.

## Dev console (`dev.html`)

Visible only to dev accounts (`config/devAccounts/<uid> = true`). It is the data-collection and
training control panel:

- **Collar capture** , live per-station status: signal (RSSI), recording state, collar battery.
- **Mode** , Training (record + upload clips) vs Production (run the model on-collar, no upload).
- **Actions to recognise** , define the behaviours to classify (eat, drink, purr, scratch, …).
  These fill each clip's label dropdown, and the trainer learns whatever set you define.
- **Train models (cloud)** , "Retrain" triggers the `train` Cloud Function on your labelled clips;
  live training status is shown below the button.
- **Data capture** , on/off: record clips back-to-back while a registered collar is in range.
- **Manual capture (ignore range)** , record whenever the collar is heard at any distance (for
  purring, which happens at rest, not at the bowl).
- **Capture range** , signal threshold + dwell before the station connects and records.
- **Recorded clips** , each row shows its label, length, and whether it has paired IMU data. Set
  the action, click a row to expand and **trim** the waveform (drag the start/end markers, Play to
  preview, Save trim), or delete it. "Delete all" clears every clip and its Storage files.

## Demo login

A read-only demo (`config/demoOwner`) points at the maintainer's own cat, so anyone can look
without signing up. The front door hides the edit / add / delete controls in demo mode, and the
database rules enforce read-only as well.

## Run locally

```
pip install -r requirements.txt
streamlit run app.py
# dashboard:   http://localhost:8501/
# front door:  http://localhost:8501/app/static/account.html
```

## Secrets

The Firebase web config (`apiKey`, etc.) is **not** secret , security is in Auth + the rules. The
database URL can go in Streamlit secrets (`st.secrets["db_url"]`) or `.streamlit/secrets.toml`,
otherwise `app.py` falls back to the `meowtion-app` URL. No service-account / admin key ever goes
in this app.

## Backend

Auth, the database, storage, and the training / upload functions all live in
[`../firebase/`](../firebase/README.md).
