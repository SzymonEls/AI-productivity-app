# Architecture

A Flask web app for managing productivity: projects with goals (Markdown), a timeline,
a manual daily plan, and time tracking. Data lives in SQLite (a single file).

## Startup

- The app is assembled by the factory function `create_app()` in [app/__init__.py:15](../app/__init__.py#L15).
  The ready object is created in [run.py:4](../run.py#L4) (`app = create_app()`), and Gunicorn uses it (`run:app`).
- Settings live in the `Config` class in [config.py:57](../config.py#L57), read from `.env` files
  (`app/instance/.env`, then `.env` in the repo root — [config.py:12-13](../config.py#L12-L13)).
- The extensions (`db`, `login_manager`, `migrate`) are shared objects in [app/extensions.py](../app/extensions.py),
  attached to the app in [app/__init__.py:27-29](../app/__init__.py#L27-L29).
- **On startup the app updates the database itself** ([app/__init__.py:47-49](../app/__init__.py#L47-L49)).
  On a server (Docker) this is disabled via `SKIP_DB_BOOTSTRAP=1`. Details in "Non-obvious things".

## Directory map

| Path | What it does |
|---|---|
| [app/__init__.py](../app/__init__.py) | Assembles the app; error handling, Jinja filters, database update at startup. |
| [config.py](../config.py) | Settings and reading environment variables from `.env`. |
| [app/extensions.py](../app/extensions.py) | Shared Flask extension objects. |
| [app/models.py](../app/models.py) | Definitions of all database tables + loading the session user. |
| [app/markdown_utils.py](../app/markdown_utils.py) | Markdown → HTML conversion with extras (checkboxes, colored sections). |
| [app/auth/](../app/auth/) | Registration, login, logout, password change. |
| [app/main/](../app/main/) | Home page + PWA files (manifest, service worker). |
| [app/ai/](../app/ai/) | **Manual** daily-plan builder (despite the name — no AI). |
| [app/projects/](../app/projects/) | Projects: CRUD, archiving plan sections, saving the timeline. |
| [app/time_tracking/](../app/time_tracking/) | Time tracking: `routes.py` + `service.py` (time/timezone logic). |
| [app/templates/](../app/templates/), [app/static/](../app/static/) | HTML views (Jinja) and CSS/JS. |
| [app/instance/](../app/instance/) | Local `.env`, secrets, the SQLite database file (not in git). |
| [migrations/](../migrations/) | Database change history (Alembic). |

Each app feature = a blueprint package `app/<name>/` with an empty `__init__.py` and `routes.py`.
Blueprints are registered in [app/__init__.py:38-42](../app/__init__.py#L38-L42).

## Request flow

The same pattern everywhere (example: editing a project):
1. URL → a function in `routes.py`.
2. `@login_required` checks the login; the helper `_get_user_project_or_404`
   ([app/projects/routes.py:15](../app/projects/routes.py#L15)) checks it is the current user's resource.
3. Read from `request.form`, manual validation, save: `db.session.commit()` inside `try/except SQLAlchemyError` with `rollback()`.
4. Response: an HTML page (`render_template`/`redirect` + `flash`) **or** JSON (`jsonify`) when the request comes in the background (fetch).

## Data model

All tables are in [app/models.py](../app/models.py). All of them have `created_at`/`updated_at` (UTC).

- **User** — username, email (both unique), hashed password.
- **Project** — `title`, `short_goal`, `frequency`, `long_goal` (Markdown), `archived_long_goal`,
  the flags `is_starred`/`is_private`/`is_archived`.
- **ProjectTimeEntry** — a work session for a project (`started_at`/`ended_at`, `description`).
  `project_id` is optional and **has no cascade**: deleting a project orphans the entries instead of deleting them;
  `project_title_snapshot` remembers the project's name ([app/models.py:98-131](../app/models.py#L98-L131)).
- **ProjectTimelineGroup** — a group (column) on the timeline; the `is_backlog` flag = "off timeline".
- **ProjectTimelineItem** — a tile: a project or a note (`item_type` = `"project"`/`"note"`).
- **DailyPlan** — **one plan per user** (`user_id` unique), overwritten on every save.

The schema in the code matches the latest migration (`20260705_0015`).

## Responsibility boundaries

- **Business logic and database access live inside the `routes.py` functions.** There is no separate service/repository layer.
- **The only exception:** time and timezone calculations are extracted into [app/time_tracking/service.py](../app/time_tracking/service.py).
- **Presentation:** [app/markdown_utils.py](../app/markdown_utils.py) (Markdown→HTML) + Jinja templates.
- **Configuration:** only [config.py](../config.py) reads environment variables.

## Non-obvious things

1. **The database updates itself when the app starts.** Importing `app` runs migrations + possibly table creation
   ([app/__init__.py:47-49](../app/__init__.py#L47-L49)). Disabled by `SKIP_DB_BOOTSTRAP=1` (Docker) so workers don't race.
2. **Two parallel ways of changing the schema.** Besides Alembic migrations, the `initialize_database` function
   ([app/__init__.py:314-484](../app/__init__.py#L314-L484)) adds missing columns with raw `ALTER TABLE`.
   This duplicates migrations — it exists so that old local SQLite files keep working. **Do not extend this block** — make new changes with a migration.
3. **The `ai` folder contains no AI.** The daily plan is built manually ([app/ai/routes.py](../app/ai/routes.py)).
   `OPENAI_API_KEY` ([config.py:75](../config.py#L75)) and the `requests` library ([requirements.txt:7](../requirements.txt#L7)) are present but unused.
4. **The plan-section "archive" is not a table.** When you archive a project plan section, the text is cut out of `long_goal` and appended to `archived_long_goal`
   via character offsets ([app/projects/routes.py:596-630](../app/projects/routes.py#L596-L630)).
5. **`_get_or_create_timeline` exists in two files** and behaves differently
   ([app/ai/routes.py:107](../app/ai/routes.py#L107) vs [app/projects/routes.py:501](../app/projects/routes.py#L501)).
   Both **write to the database during a GET** (they seed the timeline). When changing one, check the other.
6. **The side menu queries the database on every render** ([app/__init__.py:57-173](../app/__init__.py#L57-L173)) —
   a few queries added to every HTML page; wrapped in `try/except` so it doesn't break the view.
7. **Save on tab close** — `edit_project` recognizes the `_beacon=1` field and responds "silently"
   (204/400/500 without `flash`/redirect, [app/projects/routes.py:150-184](../app/projects/routes.py#L150-L184)).
8. **Time is stored in UTC (naive)**, converted to `CALENDAR_TIMEZONE` only at display time
   ([app/time_tracking/service.py](../app/time_tracking/service.py)). Sensitive — easy to get wrong when changing things.

Things not determined (literally "I don't know"):
- [app/templates/icons.html](../app/templates/icons.html) is not rendered by anything — purpose unknown.
- `app.config.get("SKIP_DB_BOOTSTRAP")` in [app/__init__.py:221](../app/__init__.py#L221) references a key
  that `Config` never sets — only the environment-variable variant works.
