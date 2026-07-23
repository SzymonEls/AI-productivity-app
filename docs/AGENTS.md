# AGENTS.md

A Flask web app for managing productivity (projects, a timeline, a daily plan, time tracking),
with data in SQLite. The code was written largely with the help of an LLM.

- **Structure and flow** are described in [ARCHITECTURE.md](ARCHITECTURE.md).
- **Conventions and the change checklist** are in [CHANGE-CHECKLIST.md](CHANGE-CHECKLIST.md).
- **A tutorial for adding a feature** is in [adding-a-feature.md](adding-a-feature.md).

## Hard rule

Before finishing ANY change, go through the matching section in
[CHANGE-CHECKLIST.md](CHANGE-CHECKLIST.md) (part B, "Definition of done") and tick off
every item. Follow the conventions in part A — verify them in the referenced example files,
do not guess from general Flask knowledge.

## What not to touch (and why)

- **The raw `ALTER TABLE` in `initialize_database`** ([app/__init__.py:314-484](../app/__init__.py#L314-L484)) —
  this is an older backward-compatibility mechanism for local databases. Change the schema with an Alembic MIGRATION, not here.
- **The database auto-bootstrap at startup** ([app/__init__.py:47-49](../app/__init__.py#L47-L49)) and the
  `SKIP_DB_BOOTSTRAP` switch — deliberately disabled in Docker so workers don't race. Don't change this logic in passing.
- **`OPENAI_API_KEY` and the `requests` package** — present but unused. Don't build assumptions on them;
  don't remove them without confirming with the repo owner.
- **The `ai` module name** — despite the name it has no AI integration; it's a manual daily-plan builder. Don't "fix" the name.
- **UTC time handling** in [app/time_tracking/service.py](../app/time_tracking/service.py) — dates are stored
  naive as UTC and converted only at display time. Keep this pattern (`ensure_utc`); don't mix timezones in the database.

When something can't be determined from the code — write plainly "I don't know" / "TODO: to be confirmed", instead of guessing.
