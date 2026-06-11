# AI Productivity App

A Flask-based productivity application for managing projects, planning work, reviewing calendar commitments, and tracking focused time. The app combines classic project management features with AI-assisted planning, local history, iCal calendar subscriptions, and per-project work timers.

## What It Does

AI Productivity App is designed as a personal planning workspace. Each user can create projects, describe goals, organize work on a timeline, generate or write daily plans, connect external calendars through private iCal links, and measure how much time is spent on each project.

The application stores its data in a local SQLite database by default and can be run locally or deployed with Docker and Gunicorn.

## Features

- User registration, login, logout, and session management with Flask-Login.
- Per-user project dashboard with starred projects, private projects, editable goals, work frequency, and long-form Markdown project plans.
- Project detail pages with inline editing, AI project organization, and daily time summary.
- Timeline workspace for grouping projects and notes into a custom planning layout.
- Manual daily planning flow that lets users select projects, write tasks, save the plan as Markdown, and pin it to the home view.
- AI daily planning that sends a prompt plus starred project context to OpenAI and stores the generated Markdown response.
- AI project organization that updates a project's short goal, frequency, and long plan based on the user's prompt.
- AI history with saved request payloads, generated responses, editable plans, and pinning for home visibility.
- Calendar page that reads saved iCal subscription URLs and builds a daily agenda view.
- Calendar settings for adding and removing per-user iCal sources.
- Time tracking with one active project timer, session descriptions, daily totals, project filters, editable entries, and simple chart data.
- Markdown rendering for AI output and project plans.
- SQLite persistence with SQLAlchemy models and Flask-Migrate/Alembic migrations.
- Docker setup for VPS deployment with a persistent instance volume.

## Tech Stack

- Python
- Flask
- Flask-SQLAlchemy
- Flask-Login
- Flask-Migrate / Alembic
- SQLite by default
- Gunicorn for containerized production serving
- iCal parsing with `icalendar` and `recurring-ical-events`
- Markdown rendering with `Markdown`
- OpenAI integration through direct HTTP requests

## Project Structure

```text
app/
  ai/              AI planning routes and service logic
  auth/            Login, registration, and logout routes
  calendar/        iCal subscription and daily calendar views
  main/            Home and root routes
  projects/        Project dashboard, CRUD, and timeline routes
  time_tracking/   Project timer and time entry routes
  templates/       Jinja templates
  static/          CSS and frontend assets
  instance/        Local environment, secrets, and SQLite database
migrations/        Alembic migration history
config.py          Application configuration
run.py             Flask entry point
Dockerfile         Production image definition
docker-compose.yml VPS-oriented compose configuration
```

## Configuration

Create a local environment file from the example:

```bash
cp app/instance/.env.example app/instance/.env
```

Important settings:

```env
SECRET_KEY=change-me
DATABASE_URL=sqlite:///app/instance/app.db
REGISTRATION_ENABLED=true
AI_ENABLED=false
CALENDAR_ENABLED=false
DEFAULT_LOGIN_EMAIL=
DEFAULT_LOGIN_PASSWORD=
CALENDAR_TIMEZONE=Europe/Warsaw

OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT=30
OPENAI_PROJECT_TIMEOUT=90
OPENAI_TEMPERATURE=0.7
OPENAI_PROJECT_TEMPERATURE=0.5
```

AI features require `OPENAI_API_KEY` and `AI_ENABLED=true`. Set `AI_ENABLED=false` to disable the AI planning module for an instance. Set `CALENDAR_ENABLED=false` to disable iCal calendar pages and event loading. The home page version is read from the repository `VERSION` file, so it updates with application code.

## Local Development

Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Apply database migrations:

```bash
flask --app run.py db upgrade
```

Start the development server:

```bash
flask --app run.py run
```

Open the app at:

```text
http://127.0.0.1:5000
```

## PWA Installation

The app includes an online-only PWA setup: a web app manifest, install icons, and a service worker that always uses the network and does not cache pages for offline use.

For mobile installation, open the app over HTTPS. Desktop Chrome treats `localhost` as secure during development, but a phone opening the app through a local network address such as `http://192.168.x.x:5000` will not register the service worker.

On a fresh local database, the app can also bootstrap empty tables automatically. Once migrations are in use, schema changes should be handled through Flask-Migrate.

## Docker / VPS Deployment

The repository includes a Docker setup intended for server deployment:

- The Flask app is served by Gunicorn on port `8000`.
- The SQLite database and instance files are persisted through `./app/instance`.
- `docker-entrypoint.sh` runs `flask --app run.py db upgrade` before the app starts.
- `SKIP_DB_BOOTSTRAP=1` is set in Docker so schema changes are controlled by migrations.

Prepare the environment file:

```bash
cp app/instance/.env.example app/instance/.env
```

Set at least:

```env
SECRET_KEY=a-long-random-secret
OPENAI_API_KEY=your_api_key_here
APP_PORT=8000
```

Build and start:

```bash
docker compose --env-file app/instance/.env up -d --build
```

View logs:

```bash
docker compose --env-file app/instance/.env logs -f web
```

Run migrations manually if needed:

```bash
docker compose --env-file app/instance/.env exec web flask --app run.py db upgrade
```

The app will be available at:

```text
http://SERVER_IP:8000
```

For a public domain, place Nginx or another reverse proxy in front of the `web` service and proxy traffic to `127.0.0.1:8000`.

## Database Migrations

Apply existing migrations:

```bash
flask --app run.py db upgrade
```

Create a new migration after changing models:

```bash
flask --app run.py db migrate -m "Describe the schema change"
flask --app run.py db upgrade
```

## Main Data Models

- `User`: account, authentication fields, and relationships to all user-owned data.
- `Project`: title, short goal, work frequency, long Markdown plan, starred/private flags, and timestamps.
- `ProjectTimelineGroup` and `ProjectTimelineItem`: custom project timeline layout with project cards and notes.
- `AIPlan`: saved AI or manual Markdown plans, request/response payloads, target date, project snapshot, and pin state.
- `CalendarSubscription`: per-user iCal source with name and URL.
- `ProjectTimeEntry`: project timer sessions with start/end timestamps and optional descriptions.

## Notes

- Default database path: `app/instance/app.db`.
- Instance files, local secrets, and the SQLite database should not be committed.
- Each authenticated user can only access their own projects, calendars, AI history, timeline items, and time entries.
- Calendar URLs are treated as private user-owned data.
- AI output is stored locally so generated plans can be reviewed, edited, and pinned later.
