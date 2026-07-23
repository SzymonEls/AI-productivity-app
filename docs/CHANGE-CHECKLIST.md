# Change checklist

Two parts: **A. Conventions** of this repo (how things are written here) and **B. Definition of done**
(what to tick off for a given change type). Imperative mood — do exactly what it says.

---

## A. Conventions of this repo

Derived from the existing code, not from general best practices. Each one has a reference file.

### Module structure (blueprint)
Each app feature is a package `app/<name>/` with an empty `__init__.py` and a `routes.py` file.
In `routes.py` the blueprint variable is named `<name>_bp` and has `url_prefix="/<name>"`.
Register the blueprint in [app/__init__.py:38-42](../app/__init__.py#L38-L42).
**Reference:** [app/time_tracking/routes.py:28](../app/time_tracking/routes.py#L28).

### Naming
- Route files: always `routes.py` inside the module package.
- Module-private helper functions: `_` prefix (e.g. `_get_user_project_or_404`,
  `_serialize_timeline_group`). **Reference:** [app/projects/routes.py:15](../app/projects/routes.py#L15).
- Models: `CamelCase` class, `__tablename__` in plural snake_case
  (`projects`, `project_time_entries`). **Reference:** [app/models.py:60-63](../app/models.py#L60-L63).
- Boolean flags: `is_*`, `nullable=False`, `default=False`. **Reference:** [app/models.py:72-74](../app/models.py#L72-L74).
- Timestamps: `created_at`/`updated_at` with `default=lambda: datetime.now(timezone.utc)`
  (and `onupdate` for `updated_at`). **Reference:** [app/models.py:75-81](../app/models.py#L75-L81).

### Models
All models are in a SINGLE file [app/models.py](../app/models.py). Don't create per-model files.
Owner relationships: `back_populates` + `cascade="all, delete-orphan"` on the `User` side.
**Reference:** [app/models.py:20-25](../app/models.py#L20-L25).

### Endpoints
A function in `routes.py` with the decorators `@<bp>.route(...)` **and** `@login_required`
(except the auth pages and the public `main` pages).
Access to a user's data ALWAYS goes through a helper filtering by `current_user.id`
(`Project.query.filter_by(id=..., user_id=current_user.id).first_or_404()`).
**Reference:** [app/projects/routes.py:123-131](../app/projects/routes.py#L123-L131).

### API response shape (JSON)
Endpoints answering fetch return a dict with an `ok` key:
- success: `jsonify({"ok": True, ...})`
- error: `jsonify({"ok": False, "message": "..."}), <HTTP code>`

**Reference:** [app/projects/routes.py:159-207](../app/projects/routes.py#L159-L207) (`edit_project`).
"HTML" endpoints use `flash(...)` + `redirect(...)` instead of JSON.
**Reference:** [app/projects/routes.py:55-62](../app/projects/routes.py#L55-L62) (`archive_project`).

### Database error handling
Wrap saves in `try/except SQLAlchemyError:` with `db.session.rollback()` in the `except` block,
then return an error (JSON `500` or a `flash` "danger").
**Reference:** [app/projects/routes.py:99-111](../app/projects/routes.py#L99-L111).
Global 404/500 errors for fetch are turned into JSON in
[app/__init__.py:176-189](../app/__init__.py#L176-L189) — don't duplicate that in handlers.

### Validation
Manual, inside the handler function. You read `request.form.get("field", "").strip()`,
check conditions with `if/elif`, and on error `flash(..., "danger")` (HTML) or
`jsonify({"ok": False, ...}), 400` (JSON). **The repo has NO** WTForms/marshmallow/pydantic — don't add them.
**Reference (HTML):** [app/projects/routes.py:80-88](../app/projects/routes.py#L80-L88) (`create_project`),
**(JSON):** [app/ai/routes.py:34-44](../app/ai/routes.py#L34-L44).
Parse booleans from the form with the `_form_bool` helper ([app/projects/routes.py:633](../app/projects/routes.py#L633)).

### Business logic vs. database access
By default everything sits in `routes.py` (`Model.query...` queries directly in the function).
Create a separate `service.py` file only for time/timezone/aggregation logic — like in
[app/time_tracking/service.py](../app/time_tracking/service.py). Don't introduce a service layer for the rest.

### ⚠️ Two conflicting conventions in the repo (resolution)

1. **Schema evolution.** Two mechanisms exist: Alembic migrations in [migrations/](../migrations/)
   **and** raw `ALTER TABLE` in `initialize_database` ([app/__init__.py:314-484](../app/__init__.py#L314-L484)).
   **The authoritative one: Alembic migrations.** The block in `__init__.py` is backward compatibility for old databases —
   treat it as frozen and don't add new columns there.

2. **`_get_or_create_timeline` exists in two versions** ([app/ai/routes.py:107](../app/ai/routes.py#L107)
   and [app/projects/routes.py:501](../app/projects/routes.py#L501)), with a different return shape.
   **The authoritative one: the version in [app/projects/routes.py:501](../app/projects/routes.py#L501)** (handles the backlog).
   When changing the timeline logic, change both copies or deliberately leave the `ai` version untouched.

---

## B. Definition of done

Tick off the sections matching your change. Each item is a specific file/command.

### Model change (new/changed field or table)
- [ ] Change the class in [app/models.py](../app/models.py) (name and type per the conventions in part A).
- [ ] Generate the migration: `flask --app run.py db migrate -m "..."`.
- [ ] Open the new file in [migrations/versions/](../migrations/versions/) and review it; for a
      `nullable=False` column make sure there is a `server_default` (see `20260704_0012`).
- [ ] Apply it: `flask --app run.py db upgrade`.
- [ ] If you added a model, add it to the import in [app/__init__.py:31](../app/__init__.py#L31).
- [ ] Update the model list in [ARCHITECTURE.md](ARCHITECTURE.md), the "Data model" section.

### New or changed endpoint
- [ ] Add a function in the right `app/<module>/routes.py` with `@<bp>.route(...)` and `@login_required`.
- [ ] Guard access with the `_get_user_project_or_404` helper (or an equivalent filter by `current_user.id`).
- [ ] Return the response per the convention: JSON `{"ok": ...}` for fetch or `flash`+`redirect` for HTML.
- [ ] Wrap the save in `try/except SQLAlchemyError` with `rollback()` if it can fail.
- [ ] If it's a NEW module: register the blueprint in [app/__init__.py:38-42](../app/__init__.py#L38-L42) and add the import in [app/__init__.py:32-36](../app/__init__.py#L32-L36).
- [ ] Wire the action into a template in [app/templates/](../app/templates/).
- [ ] Add the endpoint to the table in [ARCHITECTURE.md](ARCHITECTURE.md) (if you keep the list there) and check it fits
      [adding-a-feature.md](adding-a-feature.md).

### New environment variable
- [ ] Add the read in [config.py](../config.py), the `Config` class (`os.environ.get(...)` with a sensible default).
- [ ] Add the variable with a comment and a default value to [.env.example](../.env.example).
- [ ] Add a row to the variables table in [README.md](../README.md), the "Environment variables" section.
- [ ] If used in Docker: add it in [docker-entrypoint.sh](../docker-entrypoint.sh) and/or
      [docker-compose.yml](../docker-compose.yml).

### User-visible behavior change
- [ ] Update the relevant template in [app/templates/](../app/templates/) and/or the style in [app/static/css/](../app/static/css/).
- [ ] If you change how a feature works: bump the number in [VERSION](../VERSION) (currently `1.4.2`) — it's shown in the UI.
- [ ] Check whether the change requires updating the feature description in [ARCHITECTURE.md](ARCHITECTURE.md).

### New dependency
- [ ] Add a pinned entry (`name==version`) to [requirements.txt](../requirements.txt) — keep the version-pinning style.
- [ ] Test a clean build: `pip install -r requirements.txt` in a fresh `.venv`.
- [ ] Check whether the new package requires a change in [Dockerfile](../Dockerfile) (the `python:3.13-slim` image).
