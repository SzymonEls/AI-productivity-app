# Architecture

A Flask web app for managing productivity: projects with goals (Markdown), three project slots
per day, a timeline, and time tracking. Data lives in SQLite (a single file).

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
| [app/markdown_utils.py](../app/markdown_utils.py) | Markdown → HTML conversion with extras (checkboxes, colored sections, `#tags` painted inside list items) + `TAG_PATTERN`, the definition of a tag. |
| [app/demo.py](../app/demo.py) | Read-only demo mode (`DEMO_MODE`) + the `seed-demo` command. Inert when off. |
| [app/projects/slots.py](../app/projects/slots.py) | Daily A/B/C slots: date arithmetic, the two-block rule, the fortnight-long planner window, the calendar forwards (a month, on the schedule page) and backwards (three weeks a page, in the archive), moving a booking between blocks, taking a day off (pushing every booking from a day on one day later), marking a booked block's session done on any day (the archive ticks past ones off) and the home page's health score. |
| [app/auth/](../app/auth/) | Registration, login, logout, password change. |
| [app/main/](../app/main/) | Home page (today's A/B/C slots, unscheduled projects, health score) + PWA files (manifest, service worker). |
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
  the flags `is_starred`/`is_private`/`is_archived`. `is_private` is a curtain, not a permission:
  the project page always renders the plan and the thoughts wrapped in a veil, but the veil is
  only drawn while **safe mode** is on — a browser-side switch (`app-safe-mode` in localStorage,
  `data-safe-mode` on `<html>`, toggled by the shield in the navbar) that lives entirely in
  [app/templates/base.html](../app/templates/base.html) and the two CSS rules keyed on it.
  [app/static/js/private-reveal.js](../app/static/js/private-reveal.js) lifts a card for five
  minutes at a time and re-veils everything when safe mode is switched on again. The text is in
  the page all along — nothing is withheld from the browser, and nothing about it is enforced
  server-side.
- **ProjectTimeEntry** — a work session for a project (`started_at`/`ended_at`, `description`).
  `project_id` is optional and **has no cascade**: deleting a project orphans the entries instead of deleting them;
  `project_title_snapshot` remembers the project's name ([app/models.py:98-131](../app/models.py#L98-L131)).
- **ProjectTimelineGroup** — a group (column) on the timeline; the `is_backlog` flag = "off timeline".
- **ProjectTimelineItem** — a tile: a project or a note (`item_type` = `"project"`/`"note"`).
- **ProjectDaySlot** — one project booked into one of a day's slots (`slot` = `"A"`/`"B"`/`"C"`).
  `is_done` marks that day's session finished - it lives on the slot, so it clears itself tomorrow.
  Unique on `(user_id, slot_date, slot)`, so a slot never holds two projects. Unlike
  `ProjectTimeEntry` it **does** cascade from `Project`: a slot left by a deleted project is an
  empty booking, not history. The rule "one slot today plus one in the future" is enforced in
  [app/projects/slots.py](../app/projects/slots.py), not by the schema.

The schema in the code matches the latest migration (`20260809_0018`).

## Responsibility boundaries

- **Business logic and database access live inside the `routes.py` functions.** There is no separate service/repository layer.
- **The only exception:** time and timezone calculations are extracted into [app/time_tracking/service.py](../app/time_tracking/service.py).
- **Presentation:** [app/markdown_utils.py](../app/markdown_utils.py) (Markdown→HTML) + Jinja templates.
- **Configuration:** only [config.py](../config.py) reads environment variables.

## Non-obvious things

0. **In Docker the instance directory is `/app/app/instance`, not `/app/instance`.**
   The image puts the repository root at `/app` ([Dockerfile:10](../Dockerfile#L10)), so the
   repo's own `app/instance` sits one level deeper — and that is where
   [config.py:8-13](../config.py#L8-L13) looks for `.env` and the database. The volume in
   [docker-compose.yml](../docker-compose.yml), the entrypoint and `DATABASE_URL` all have to
   name the same path. Until 1.5.0 they did not, and the mounted `.env` was read by nobody.
1. **The database updates itself when the app starts.** Importing `app` runs migrations + possibly table creation
   ([app/__init__.py:47-49](../app/__init__.py#L47-L49)). Disabled by `SKIP_DB_BOOTSTRAP=1` (Docker) so workers don't race.
2. **Two parallel ways of changing the schema.** Besides Alembic migrations, the `initialize_database` function
   ([app/__init__.py:314-484](../app/__init__.py#L314-L484)) adds missing columns with raw `ALTER TABLE`.
   This duplicates migrations — it exists so that old local SQLite files keep working. **Do not extend this block** — make new changes with a migration.
3. **`OPENAI_API_KEY` and the `requests` library are read but unused** ([config.py](../config.py),
   [requirements.txt](../requirements.txt)). The `ai` blueprint they were named after is gone as of 1.5.0;
   the variables stay until the repo owner decides otherwise.
4. **The plan-section "archive" is not a table.** When you archive a project plan section, the text is cut out of `long_goal` and appended to `archived_long_goal`
   via character offsets ([app/projects/routes.py:596-630](../app/projects/routes.py#L596-L630)).
5. **`_get_or_create_timeline` writes to the database during a GET** — it seeds the timeline when
   the user has none ([app/projects/routes.py](../app/projects/routes.py)). It used to exist in two
   copies; removing the `ai` blueprint in 1.5.0 left just this one.
6. **The side menu queries the database on every render** ([app/__init__.py:57-173](../app/__init__.py#L57-L173)) —
   a few queries added to every HTML page; wrapped in `try/except` so it doesn't break the view.
7. **Save on tab close** — `edit_project` recognizes the `_beacon=1` field and responds "silently"
   (204/400/500 without `flash`/redirect, [app/projects/routes.py:150-184](../app/projects/routes.py#L150-L184)).
8. **Time is stored in UTC (naive)**, converted to `CALENDAR_TIMEZONE` only at display time
   ([app/time_tracking/service.py](../app/time_tracking/service.py)). Sensitive — easy to get wrong when changing things.
9. **Demo mode installs nothing when it is off.** `register_demo_mode` ([app/demo.py](../app/demo.py)),
   called once from `create_app`, returns straight after setting `demo_mode = False` in `app.jinja_env.globals`
   unless `DEMO_MODE` is set. Only then does it register the `before_request` write guard, render
   `DEMO_DOC_PATH` (once, at startup) and add the `seed-demo` command. It deliberately stays out of
   `inject_feature_flags` — that context processor runs on every render and already queries the database,
   so the flag is a Jinja global instead. Point 5 still applies in demo mode: the guard only stops writes
   on `POST`/`PUT`/`PATCH`/`DELETE`, so the timeline still seeds itself on a GET. `seed-demo` builds the
   timeline up front, which makes that a no-op.

10. **A day off moves the bookings newest first.** `shift_bookings_forward`
    ([app/projects/slots.py](../app/projects/slots.py)) pushes every booking from the chosen day
    on one day later, so each one lands on the date the booking after it has just left. Walking
    the rows the other way round would hit the unique constraint on `(user, date, slot)` halfway
    through, and so would moving them all in one flush — hence the `flush()` per row. Two
    consequences: **a booking already marked done does not move at all** — it happened, and "done"
    belongs to a date, so moving it would file the work under a day it was not done on and quietly
    undo it (a block with one in its way is held back too, having nowhere to land) — and the shift
    can push a booking past the edge of the schedule page, which is why that page's window grows to
    the last booked day (`weeks_to_cover`) instead of being a fixed three weeks.

11. **A tag is not stored anywhere.** `#shop` in "- [ ] call the printer #shop" is text in
    `Project.long_goal` and nothing else — no table, no column, nothing to keep in step. The tag
    tag page (`/projects/tags`, linked from the home page) carries no tags of its own: it arrives
    with a spinner in the HTML and asks `/projects/tags/search`, which reads every active plan and
    groups what it finds (`_collect_tags` in [app/projects/routes.py](../app/projects/routes.py)). Three rules follow the same `TAG_PATTERN`
    ([app/markdown_utils.py](../app/markdown_utils.py)) so the views cannot disagree: a tag starts
    with a letter, may not follow a word character or "(" (so `C#` and a `](#anchor)` link target
    are not tags), and **only counts inside a list item** — which is why the block editor paints
    them in list blocks alone. The JavaScript copies of the pattern
    ([plan-block-editor.js](../app/static/js/plan-block-editor.js),
    [tag-list.js](../app/static/js/tag-list.js)) spell it with Unicode property escapes, because
    JavaScript's `\w` is ASCII and would cut `#dom-i-ogród` short.

12. **The home page's health score is a convention, not a measurement.** `system_health`
    ([app/projects/slots.py](../app/projects/slots.py)) mixes two ratios — how many of the sessions
    booked over the 7 days **before today** were marked done (A, B and C alike; an unfilled slot
    counts on neither side of it), and the share of active projects that have a next session booked —
    weighted 60/40, with the bands at 75 and 50 deciding the colour. The window and those four
    numbers are constants at the top of the file; change them there, not in the template. Two
    consequences worth knowing: today is deliberately outside the window, so the score moves in the
    morning only when yesterday was left unfinished, and a week with nothing booked scores zero on
    the sessions half rather than dividing by zero.

## What not to touch (and why)

- **The raw `ALTER TABLE` in `initialize_database`** ([app/__init__.py:314-484](../app/__init__.py#L314-L484)) —
  an older backward-compatibility mechanism for local databases. Change the schema with an
  Alembic MIGRATION, not here.
- **The database auto-bootstrap at startup** ([app/__init__.py:47-49](../app/__init__.py#L47-L49)) and the
  `SKIP_DB_BOOTSTRAP` switch — deliberately disabled in Docker so workers don't race.
  Don't change this logic in passing.
- **`OPENAI_API_KEY` and the `requests` package** — present but unused. Don't build assumptions
  on them; don't remove them without confirming with the repo owner.
- **UTC time handling** in [app/time_tracking/service.py](../app/time_tracking/service.py) — dates are stored
  naive as UTC and converted only at display time. Keep this pattern (`ensure_utc`); don't mix
  timezones in the database.

Things not determined (literally "I don't know"):
- [app/templates/icons.html](../app/templates/icons.html) is not rendered by anything — purpose unknown.
- `app.config.get("SKIP_DB_BOOTSTRAP")` in [app/__init__.py:221](../app/__init__.py#L221) references a key
  that `Config` never sets — only the environment-variable variant works.
