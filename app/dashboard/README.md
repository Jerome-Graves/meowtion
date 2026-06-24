# Dashboard (Streamlit)

One Streamlit deployment serves two same-origin pages:

| Page | File | Language | Does |
|------|------|----------|------|
| Front door | [`static/account.html`](static/account.html) | JS | log in / sign up / demo login, manage account (incl. delete), register devices over Web Serial |
| Dashboard | [`app.py`](app.py) | Python | shows the signed-in owner's cats and stations, live |

## Why two pages

Device registration needs the **Web Serial API**, which is browser JavaScript and
won't run inside Streamlit's Python (or its sandboxed component iframes). So the
front door is a static JS page, served from the **same origin** by Streamlit's
static file serving (`enableStaticServing`, see `.streamlit/config.toml`).

## Single login

You log in once on the front door. It writes the Firebase token into a same-origin
**cookie**, and `app.py` reads it with `st.context.cookies`, so clicking **Open
dashboard** doesn't ask you to log in again. No token in the URL.

## Demo login

A read-only demo account points at the maintainer's own cat, so anyone can look
without signing up. The front door hides the edit / add / delete controls in demo
mode; the database rules enforce read-only as well.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
# dashboard:   http://localhost:8501/
# front door:  http://localhost:8501/app/static/account.html
```

## Secrets
The Firebase web config (apiKey, etc.) is **not** secret, security is in Auth +
rules. The database URL goes in Streamlit secrets (`st.secrets["db_url"]`) or
`.streamlit/secrets.toml`. No service-account / admin key ever goes in this app.

## See also
- Data shape it reads: [../../docs/data-schema.md](../../docs/data-schema.md)
- The whole flow: [../../docs/user-journey.md](../../docs/user-journey.md)
- Security model: [../../docs/security.md](../../docs/security.md)
