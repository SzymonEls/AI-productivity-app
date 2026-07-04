# AI Productivity App

A Flask-based productivity application for managing projects, planning work, and tracking focused time.

## What It Does

AI Productivity App is designed as a personal planning workspace. Each user can create projects, describe goals, organize work on a timeline, write daily plans manually, and measure how much time is spent on each project.

The application stores its data in a local SQLite database by default and can be run locally or deployed with Docker and Gunicorn.

## Features

- User registration, login, logout, and session management with Flask-Login.
- Per-user project dashboard with starred projects, private projects, editable goals, work frequency, and long-form Markdown project plans.
- Project detail pages with inline editing and daily time summary.
- Timeline workspace for grouping projects and notes into a custom planning layout.
- Manual daily planning flow that lets users select projects, write tasks, and save the plan as Markdown. Saving a new plan replaces the one shown on the home view; only one daily plan is kept at a time.
- Time tracking with one active project timer, session descriptions, daily totals, project filters, editable entries, and simple chart data.
- Markdown rendering for daily plans and project plans.
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
- Markdown rendering with `Markdown`

## Project Structure

```text
app/
  ai/              Manual daily planning routes
  auth/            Login, registration, and logout routes
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
DEFAULT_LOGIN_EMAIL=
DEFAULT_LOGIN_PASSWORD=
CALENDAR_TIMEZONE=Europe/Warsaw

# Reserved for a future AI feature; unused by the app today.
OPENAI_API_KEY=
```

`CALENDAR_TIMEZONE` sets the local timezone used for "today" boundaries in time tracking. The home page version is read from the repository `VERSION` file, so it updates with application code.

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
- `DailyPlan`: the single saved daily plan per user (title, target date, Markdown content), replaced each time a new plan is saved.
- `ProjectTimeEntry`: project timer sessions with start/end timestamps and optional descriptions.

## Notes

- Default database path: `app/instance/app.db`.
- Instance files, local secrets, and the SQLite database should not be committed.
- Each authenticated user can only access their own projects, daily plan, timeline items, and time entries.
