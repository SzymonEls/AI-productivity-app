# Productivity App MVP

A minimal Flask productivity/project tracking app with authentication, project CRUD, and an iCal-based daily calendar view.

## Features

- User registration, login, and logout
- SQLite database via SQLAlchemy
- Flask-Login session management
- Project dashboard
- Create, view, edit, and delete projects
- Calendar tab with daily plan view built from saved iCal calendar URLs
- Application factory pattern and blueprints for easy expansion
- Flask-Migrate setup for future schema changes

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `instance/.env.example` to `instance/.env` and fill in your settings.

For AI features, set at least:

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT=30
```

4. Start the app:

```bash
flask --app run.py run
```

The app will automatically create tables on first run if the database is empty.

5. Open `http://127.0.0.1:5000`

6. Log in, open `Kalendarz`, then use `Ustawienia kalendarzy` to add one or more secret iCal URLs.

## Docker / VPS Deployment

The repository includes a production-oriented Docker setup:

- `web`: Flask app served by Gunicorn on port `8000`
- SQLite database stored in a persistent Docker volume
- `docker-entrypoint.sh`: runs `flask --app run.py db upgrade` automatically before Gunicorn starts

On the VPS:

```bash
cp instance/.env.example instance/.env
```

Edit `instance/.env` and set at least:

```env
SECRET_KEY=a-long-random-secret
OPENAI_API_KEY=your_api_key_here
APP_PORT=8000
```

Build and start:

```bash
docker compose --env-file instance/.env up -d --build
```

Check logs:

```bash
docker compose --env-file instance/.env logs -f web
```

Run migrations manually if needed:

```bash
docker compose --env-file instance/.env exec web flask --app run.py db upgrade
```

The app will be available on `http://SERVER_IP:8000` unless `APP_PORT` is changed.

For a public domain, put Nginx or another reverse proxy in front of the `web` service and proxy traffic to `127.0.0.1:8000`.

### Docker Notes

- Docker Compose uses `sqlite:////app/instance/app.db`, so the database file lives inside the persistent `instance_data` volume.
- `SKIP_DB_BOOTSTRAP=1` is set in Docker so schema changes are handled by Alembic migrations instead of `db.create_all()`.
- Flask instance files and the SQLite database are stored in the named volume `instance_data`.

## Migrations

This repository now includes a ready-to-use Flask-Migrate / Alembic setup in `migrations/`.

Apply the existing schema migration:

```bash
flask --app run.py db upgrade
```

Create a new migration after model changes:

```bash
flask --app run.py db migrate -m "Describe the schema change"
flask --app run.py db upgrade
```

## Notes

- The default database path is `instance/app.db`.
- Set `SECRET_KEY` in your environment for production use.
- Set `CALENDAR_TIMEZONE` if you want the day view rendered in a timezone other than `Europe/Warsaw`.
- AI features use the OpenAI Responses API and save generated plans in local history.
- Each user stores their own list of iCal subscriptions in the database.
- The project is structured so you can later add REST APIs, more project fields, or AI-related modules cleanly.
