# AI productivity app

A Flask app for managing productivity: projects, a timeline, a daily plan, and time tracking.
Data lives in SQLite. The structure is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md);
conventions and the change checklist are in [docs/CHANGE-CHECKLIST.md](docs/CHANGE-CHECKLIST.md).

## Requirements

- Python 3.13 (the Docker image uses `python:3.13-slim`; lower 3.x versions will likely work but are untested).
- `pip` to install the dependencies from [requirements.txt](requirements.txt).
- No separate database server needed — a local SQLite file is used by default.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell/cmd)
# source .venv/bin/activate     # Linux / macOS

pip install -r requirements.txt
```

Create a local environment file (variables are described below):

```bash
cp .env.example app/instance/.env
```

> The app reads `app/instance/.env` first, then `.env` in the repo root. One of them is enough.

## Running (dev mode)

```bash
flask --app run.py run
```

or directly:

```bash
python run.py
```

The app starts at `http://127.0.0.1:5000`.

> `python run.py` enables `debug=True` but **without** auto-reload on file changes
> (`use_reloader=False`, [run.py:8](run.py#L8)) — restart the process manually after changing code.
> On the first run against an empty database, the app creates the tables and applies migrations
> automatically (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), the "Non-obvious things" section).

## Environment variables

The full list is in [.env.example](.env.example). The most important ones:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-secret-key-change-me` | Signing sessions. **Set your own secret in production.** |
| `DATABASE_URL` | `sqlite:///app/instance/app.db` | Database address. |
| `REGISTRATION_ENABLED` | `true` | Whether registration is allowed. |
| `REMEMBER_COOKIE_DAYS` | `30` | How many days "remember me" lasts. |
| `APP_VERSION` | from the `VERSION` file | Version shown in the app. |
| `DEFAULT_LOGIN_EMAIL` | (empty) | Pre-fills the email in the login form. |
| `DEFAULT_LOGIN_PASSWORD` | (empty) | Pre-fills the password in the login form. |
| `CALENDAR_TIMEZONE` | `Europe/Warsaw` | Timezone for "day" boundaries in time tracking. |
| `DEMO_MODE` | `false` | `true` turns the installation into a read-only demo (see below). |
| `DEMO_DOC_PATH` | `README.md` | Markdown file rendered on the login page in demo mode. |
| `DEMO_DOC_BASE_URL` | the GitHub repo | Address that relative links in that file are rewritten to. |
| `DEMO_BLOCK_MESSAGE` | `Demo mode - changes are disabled.` | Shown when a demo visitor tries to save. |
| `DEMO_BANNER_MESSAGE` | `Read-only portfolio demo — …` | Banner text above every page; empty hides the banner. |
| `OPENAI_API_KEY` | (empty) | Read, but **currently unused** (reserved for the future). |
| `SKIP_DB_BOOTSTRAP` | (unset) | `1` disables the automatic database update at startup (set in Docker). |

Variables used only when running in Docker: `APP_PORT`, `GUNICORN_WORKERS`, `GUNICORN_TIMEOUT`.

## Demo mode

`DEMO_MODE=true` turns an installation into a public, read-only demo:

- every `POST`/`PUT`/`PATCH`/`DELETE` is refused, so visitors can open every screen but
  change nothing (logging in and out still works);
- the login page becomes a landing page: the credentials from `DEFAULT_LOGIN_EMAIL` /
  `DEFAULT_LOGIN_PASSWORD` are pre-filled and `DEMO_DOC_PATH` is rendered below the form;
- a "Demo" banner with the text from `DEMO_BANNER_MESSAGE` sits above every page
  (set it to an empty value to drop the banner);
- `flask --app run.py seed-demo` fills the database with sample content
  (`--reset` rebuilds it). Docker runs this at startup when `DEMO_MODE=1`.

While `DEMO_MODE` is off, none of this is installed: no request hook is registered and no
file is read, so a normal installation runs exactly as it did before the feature existed
([app/demo.py](app/demo.py)).

Set `REGISTRATION_ENABLED=false` alongside it, and deploy with
[docker-compose.demo.yml](docker-compose.demo.yml) — step by step in
[docs/demo-deployment.md](docs/demo-deployment.md).

## Database migrations

Apply existing migrations (bring the database up to the latest schema):

```bash
flask --app run.py db upgrade
```

After changing the models in [app/models.py](app/models.py), generate a new migration and apply it:

```bash
flask --app run.py db migrate -m "Describe the schema change"
flask --app run.py db upgrade
```

> A step-by-step guide to adding a field and an endpoint is in [docs/adding-a-feature.md](docs/adding-a-feature.md).
