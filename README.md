# Productivity app

A self-hosted Flask app for planning the week: projects with a Markdown plan, a drag-and-drop
timeline, three project slots a day and a stopwatch for tracked time. One SQLite file, one
container, no external services.

![The project view: a Markdown plan rendered as colour-coded, checkable sections](https://raw.githubusercontent.com/SzymonEls/AI-productivity-app/main/docs/productivity.png)

## What it does

- **Projects** — each one has a short goal, a cadence and a long plan written in Markdown.
  Headings become steps, checkboxes stay checkable in the rendered view, and a finished
  section can be archived out of the plan without leaving the page. A project marked private
  carries no padlock anywhere — that would point it out. Switch on **safe mode** (the shield next
  to the theme switch) and such a project opens with its plan and its thoughts behind a button
  each; a reveal is remembered for five minutes, and reaching for the shield again drops it.
- **Tags** — write `#anything` in a list item of a plan and it becomes a tag. Nothing is stored
  as a tag: the home page's tag list reads the plans when you open it and groups what it finds,
  and every entry leads back to the line it came from. Tags are picked out in the plan itself too.
- **Timeline** — projects and free-form notes arranged in columns you drag between; a backlog
  column holds whatever is off the timeline.
- **Day slots** — every day has slots A, B and an optional C, one project each. The home page
  shows what is in them, the first heading of each plan and today's tracked time against a target.
  Below that sits a health ring, 0 to 100: how many of the booked sessions in the week before today
  were ticked off, mixed with how much of the project list has a next session planned.
- **Schedule** — a month of day sheets, each showing its A/B/C blocks in the same colours as
  the home page: dashed grey while free, amber once booked, green when the session is done. The
  sheets are a live board with no edit mode to switch on: click a free block to fill it, drag a
  project between blocks — dropping one on a taken block swaps the two — or free a block with its ×.
  "Day off", next to the archive link, asks for a date and frees it: that day and everything
  planned after it move one day later — bar a session already ticked off, which stays on the day
  it happened — and the page shows as many weeks as it takes to keep the last booking in view.
  **Archive** shows the same sheets for days already gone, three weeks a page, back to the first
  booking; it is a record, so nothing there can be booked, moved or freed — but its ✓ still works,
  so a session finished on Tuesday can be ticked off on Thursday and counts towards the health
  ring like any other.
- **Time tracking** — start/stop a timer per project, with daily and weekly totals. Deleting a
  project keeps its entries: they hold a snapshot of the title, so past weeks stay correct.
- **Installable (PWA)** and mobile-first, because most of the ticking off happens on a phone.

## Stack

Flask 3 · SQLAlchemy + Alembic · Flask-Login · SQLite · Jinja templates with vanilla JS ·
Gunicorn in Docker behind nginx.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp app/instance/.env.example app/instance/.env      # every setting is documented in there
python run.py
```

The app starts at `http://127.0.0.1:5001` and creates the SQLite database and its tables on
first run. Register an account, or set `DEFAULT_LOGIN_EMAIL` / `DEFAULT_LOGIN_PASSWORD` to
pre-fill the login form.

> Port 5001 rather than Flask's usual 5000: on macOS the AirPlay Receiver in Control Center
> listens on `*:5000` and answers every request with a 403.

## Deployment

An instance is a directory with a `docker-compose.yml` and an `app/instance/.env`; the same
compose file serves the private instance and the public demo, which differ only in that file.
Nothing is published on the host — the container has a pinned name and a reverse proxy reaches
it by that name on port 8000, so several instances can share one server. On first boot the
entrypoint generates a `SECRET_KEY`, runs the migrations and, in demo mode, seeds sample
content; all three are idempotent, so redeploys leave the data alone. There is more info about demo in demo/example.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — structure, data model, request flow and the
  non-obvious parts.
- [docs/CHANGE-CHECKLIST.md](docs/CHANGE-CHECKLIST.md) — the repo's conventions and a
  definition of done per change type.
