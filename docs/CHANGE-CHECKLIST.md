# Change checklist

Two parts: **A. Conventions** of this repo (how things are written here) and **B. Definition of done**
(what to tick off for a given change type). Imperative mood — do exactly what it says.
The structure and flow of the app are described in [ARCHITECTURE.md](ARCHITECTURE.md), including
the list of things not to touch.

## Hard rule

Before finishing ANY change, go through the matching section of part B below and tick off every
item. Follow the conventions in part A — verify them in the referenced example files, do not
guess from general Flask knowledge. When something can't be determined from the code, write
plainly "I don't know" / "TODO: to be confirmed" instead of guessing.

---

## A. Conventions of this repo

Derived from the existing code, not from general best practices. Each one has a reference file.

### Where a change belongs
The server does three things: authenticate, store, and answer what changed. If a
change is about **a rule** - when a slot may be booked, how a plan renders, what
a tag is - it belongs in `client/src/domain/`, not in Python. The server has no
opinion about those any more.
**Reference:** [client/src/domain/slots.ts](../client/src/domain/slots.ts).

### Server module structure
`app/api/` holds the whole API: `routes.py` for pull/push/export, `auth.py` for
signing in, and the supporting modules beside them. New endpoints go there
rather than into a new blueprint.
**Reference:** [app/api/routes.py](../app/api/routes.py).

### Naming
- Module-private helpers: `_` prefix.
- Models: `CamelCase` class, plural snake_case `__tablename__`.
- Boolean flags: `is_*`, `nullable=False`, `default=False`.
- Timestamps: `default=lambda: datetime.now(timezone.utc)` (and `onupdate`).

### Models
All models are in a SINGLE file [app/models.py](../app/models.py). A new
synchronised table inherits `SyncMixin` and calls `sync_table_args("<table>")`,
and names its content columns in `__sync_payload__` so a deletion empties them.

### Endpoints
`@api_bp.route(...)` **and** `@login_required`. Access to a user's data always
filters by `current_user.id`. Success is `jsonify({"ok": True, ...})`; failure is
`jsonify({"ok": False, "message": "..."}), <code>`, with a `reason` when the
client has to tell cases apart.

### Writes
Never `db.session.delete` on a synchronised row - use `soft_delete`. Never set
`rev` by hand: the `before_flush` listener stamps every write. Wrap saves in
`try/except SQLAlchemyError` with `rollback()`.

### Client
Every write goes through `client/src/db/mutate.ts`, so the change and its outbox
entry land in one transaction. Views read through `live()` from
[client/src/lib/live.svelte.ts](../client/src/lib/live.svelte.ts) and never
fetch. Domain functions stay pure: they return what should change, and the view
writes it.

### Validation
Manual, inside the handler. The repo has NO WTForms/marshmallow/pydantic -
don't add them.

### ⚠️ Conflicting convention in the repo (resolution)

**Schema evolution.** Two mechanisms exist: Alembic migrations in [migrations/](../migrations/)
**and** raw `ALTER TABLE` in `initialize_database` ([app/__init__.py:314-484](../app/__init__.py#L314-L484)).
**The authoritative one: Alembic migrations.** The block in `__init__.py` is backward compatibility for old databases —
treat it as frozen and don't add new columns there.

(The second conflict listed here — two copies of `_get_or_create_timeline` — went away in 1.5.0
when the `ai` blueprint was removed. Only the version in `app/projects/routes.py` remains.)

---

### Tests

There is a `tests/` directory now, run with `pytest` (dependencies in `requirements-dev.txt`,
which includes `requirements.txt`). It is not exhaustive and does not cover the Jinja pages; what
it does cover is the part with no other safety net — the synchronisation rules and the migration
that runs against real data.

Tests build their database **by running the migrations**, never `db.create_all()`. A suite built on
`create_all` passes happily while the migration that has to run on the production database is
broken, which is the one failure that actually costs data.

Run **both** suites before finishing: `pytest` for the server, and
`cd client && npm run test` for the ports and the write path. A port from Python
is checked against output captured from the Python it replaces - see
`client/src/domain/__golden__*.json`; regenerate those rather than editing them
by hand.

## B. Definition of done

Tick off the sections matching your change. Each item is a specific file/command.

### Model change (new/changed field or table)
- [ ] Change the class in [app/models.py](../app/models.py).
- [ ] If it is synchronised: inherit `SyncMixin`, use `sync_table_args`, and list
      its content columns in `__sync_payload__`.
- [ ] Describe it on **both** sides of the wire:
      [app/api/protocol.py](../app/api/protocol.py) and
      [client/src/sync/types.ts](../client/src/sync/types.ts). These two drifting
      apart is the failure this codebase is most exposed to.
- [ ] Add the store to [client/src/db/schema.ts](../client/src/db/schema.ts).
- [ ] Generate the migration: `flask --app run.py db migrate -m "..."`.
- [ ] Review it; for a `nullable=False` column make sure there is a
      `server_default` (see `20260704_0012`). Backfill in batches, and make it
      safe to run twice (see `20260901_0021`).
- [ ] Apply it: `flask --app run.py db upgrade`.
- [ ] Confirm the model and the database agree: `flask --app run.py db check`
      against a copy of a real database. It has to say "No new upgrade
      operations detected". If autogenerate proposes dropping something the
      database genuinely needs, DECLARE it on the model - deleting the proposal
      from the migration by hand leaves the drift in place.
- [ ] If you added a model, add it to the import in `app/__init__.py`.
- [ ] Update the Data model section in [ARCHITECTURE.md](ARCHITECTURE.md).

### New or changed view
- [ ] A file in [client/src/routes/](../client/src/routes/), reading through
      `live()` and writing through `db/mutate.ts`.
- [ ] Add the route to
      [client/src/lib/router.svelte.ts](../client/src/lib/router.svelte.ts) and
      the navigation in `client/src/App.svelte`.
- [ ] If it shows a private project's own words, wrap them in `PrivateVeil`.
- [ ] `npm run build`, or the server serves the previous bundle.

### New environment variable
- [ ] Add the read in [config.py](../config.py), the `Config` class (`os.environ.get(...)` with a sensible default).
- [ ] Add the variable with a comment and a default value to [app/instance/.env.example](../app/instance/.env.example)
      — that file is the reference list the README points at, so it has to stay complete.
- [ ] If used in Docker: add it in [docker-entrypoint.sh](../docker-entrypoint.sh) and/or
      [docker-compose.yml](../docker-compose.yml).

### User-visible behavior change
- [ ] Update the relevant template in [app/templates/](../app/templates/) and/or the style in [app/static/css/](../app/static/css/).
- [ ] If you change how a feature works: bump the number in [VERSION](../VERSION) (currently `2.0.0`) — it's shown in the UI.
      One number per release, not per change: a batch of features that ship together share it.
- [ ] Check whether the change requires updating the feature description in [ARCHITECTURE.md](ARCHITECTURE.md).

### New dependency
- [ ] Add a pinned entry (`name==version`) to [requirements.txt](../requirements.txt) — keep the version-pinning style.
- [ ] Test a clean build: `pip install -r requirements.txt` in a fresh `.venv`.
- [ ] Check whether the new package requires a change in [Dockerfile](../Dockerfile) (the `python:3.13-slim` image).
