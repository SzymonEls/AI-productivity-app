# Architecture

A local-first planning application. Everything you see is drawn from a copy of
your data held in the browser; the server keeps the shared copy and hands out
the differences. Projects with a Markdown plan, three slots a day, a timeline
board and time tracking.

## The shape of it

Two halves, and one thing crossing between them.

- **The client** (`frontend/`) — Svelte 5 and TypeScript, built by Vite into
  `backend/app/static/client/`. It owns every view, every rule about what may be booked
  when, and its own copy of the data in IndexedDB. It works with no network.
- **The server** (`backend/app/`) — Flask. It authenticates, stores the shared copy, and
  answers two questions: what changed since a given point, and here is what I
  changed, what of it can you take. It renders no pages.
- **The protocol** (`backend/app/api/protocol.py` and `frontend/src/sync/types.ts`) — the
  same description of the same tables, written twice. Changing one without the
  other is the mistake this codebase is most exposed to.

The reasoning behind this shape, the bugs found building it and what is still
unverified are recorded in [local-first-sync.md](local-first-sync.md).

## Startup

- Factory `create_app()` in [backend/app/__init__.py](../backend/app/__init__.py); `run.py` makes
  `app = create_app()`; Gunicorn serves `run:app`.
- `Config` in [config.py](../backend/app/config.py), fed from `instance/.env` then `.env`.
- The application migrates its own database at startup, disabled in Docker with
  `SKIP_DB_BOOTSTRAP=1` so several workers do not race.
- The client is **built, not served live**: `cd frontend && npm run build`. There
  is no Node process in production. `npm run dev` exists for working on the
  frontend and proxies `/api` and `/auth` to Flask.

## Directory map

| Path | What it does |
|---|---|
| [backend/app/__init__.py](../backend/app/__init__.py) | Assembles the app; JSON errors, database update at startup. |
| [backend/app/models.py](../backend/app/models.py) | Every table, and the synchronisation columns on most of them. |
| [backend/app/api/](../backend/app/api/) | The whole of the server's job. `routes.py` (pull, push, export), `auth.py` (signing in), `protocol.py` (what crosses the wire), `revisions.py` (stamping writes, tombstones), `pruning.py`, `security.py` (CSRF). |
| [backend/app/lockout.py](../backend/app/lockout.py) | Failed sign-ins, counted per email address in the database. |
| [backend/app/clock.py](../backend/app/clock.py) | The configured time zone, and what "today" means. |
| [backend/app/shell.py](../backend/app/shell.py) | The shell, the manifest and the service worker. Nothing else. |
| [backend/app/demo.py](../backend/app/demo.py) | Read-only demo mode and the `seed-demo` command. Inert when off. |
| [backend/app/markdown_utils.py](../backend/app/markdown_utils.py) | Only the demo document still needs this; the plan is rendered in the client. |
| [frontend/src/domain/](../frontend/src/domain/) | The rules, ported from Python: `slots.ts`, `time.ts`, `markdown.ts`, `tags.ts`, `plan-sections.ts`. |
| [frontend/src/db/](../frontend/src/db/) | The local copy, and the outbox every change passes through. |
| [frontend/src/sync/](../frontend/src/sync/) | Pull, push, conflicts, and what the button knows. |
| [frontend/src/routes/](../frontend/src/routes/) | One file per view. |
| [backend/migrations/](../backend/migrations/) | Database change history (Alembic). |

## How a change travels

1. A view calls `createRow`, `updateRow` or `deleteRow` in
   [frontend/src/db/mutate.ts](../frontend/src/db/mutate.ts). The row and an entry in
   the outbox are written in **one** IndexedDB transaction. The screen updates
   from the local copy; nothing waited for a network.
2. `sync.run()` pulls, then pushes. It runs on start-up, on regaining a
   connection, when the tab comes back, once a minute, and when the button is
   pressed.
3. `POST /api/sync/push` applies what it can. Anything built on a version the
   server has moved past comes back as a conflict, and **the change stays in the
   outbox**: it is still the person's, still unsent.
4. The person settles the conflict in the dialog. Nothing is merged silently.

## Data model

All tables are in [backend/app/models.py](../backend/app/models.py), all with UTC
`created_at`/`updated_at`.

- **User** — username, email (both unique), hashed password, `session_token`
  (changing a password rotates it, which signs every other device out).
- **Project** — `title`, `short_goal` ("thoughts"), `frequency`, `long_goal`
  (Markdown), `archived_long_goal`, flags `is_starred`/`is_private`/`is_archived`.
- **ProjectTimeEntry** — `started_at`/`ended_at`/`description`. `project_id` is
  optional and does **not** cascade: deleting a project detaches its entries
  rather than destroying them, and `project_title_snapshot` keeps past weeks
  readable.
- **ProjectTimelineGroup** / **ProjectTimelineItem** — the board's columns and
  cards; `is_backlog` marks the off-timeline column.
- **ProjectDaySlot** — one project in one slot (A, B or the optional C), with
  `is_done` per slot so it resets by itself tomorrow.
- **SyncState** — per account: `last_rev`, the counter every write draws from,
  and `tombstone_floor`, how far deleted rows have been cleared away.
- **LoginAttempt** — one failed sign-in, kept only as long as it locks the door.

Every table except `User`, `LoginAttempt` and `SyncState` also carries three
columns from `SyncMixin`. The integer primary key stays where it was; these live
beside it:

- **`uid`** — a ULID minted by whoever created the row. Identity that does not
  need a server. The API never exposes the integer id; every reference across
  the wire is a uid.
- **`rev`** — the per-account counter, stamped by the server. An ordering rather
  than a clock, because two devices disagree about the time but not about which
  change came second.
- **`deleted_at`** — a tombstone. See "non-obvious things" below.

The schema in the code matches migration `20260901_0021`.

## Responsibility boundaries

- **The rules live in the client**, in `frontend/src/domain/`, as pure functions
  that work out what should change and hand it back. The caller writes it
  through `db/mutate.ts`.
- **The server enforces one invariant**: one live booking per (user, date, slot),
  as a partial unique index. The two-block rule and everything else about
  planning is a client rule now. For a single-person self-hosted application
  that is a deliberate trade; it is a real change to the trust model.
- **Configuration**: only [config.py](../backend/app/config.py) reads environment variables.

## Non-obvious things

0. **The instance directory sits at the project root, not inside the package.**
   `instance/` holds the live database, the real `.env` and the secrets - data
   that outlives the code beside it. In Docker the repository root is `/app`, so
   it is `/app/instance`, and the volume, the entrypoint and `DATABASE_URL` must
   all name that. A deployment created before 2.1 mounted `/app/app/instance`;
   move the directory on the host and correct `DATABASE_URL` in its `.env`.

1. **The database updates itself at startup**, disabled in Docker with
   `SKIP_DB_BOOTSTRAP=1`. Don't change that in passing.

2. **Two parallel schema mechanisms.** `initialize_database` in
   [backend/app/__init__.py](../backend/app/__init__.py) adds missing columns with raw
   `ALTER TABLE`, kept so old local files still open. **Do not extend it** - make
   new changes with a migration.

3. **A deletion is a row, not an absence.** `soft_delete` in
   [backend/app/api/revisions.py](../backend/app/api/revisions.py) sets `deleted_at`, stamps a
   revision, and **empties the content columns immediately** (`__sync_payload__`
   on each model), so a deleted private plan stops existing on the server at the
   next sync. What is kept for the retention window is the bare fact that the
   uid is gone. `NOT NULL` columns are emptied to `""`.

4. **Tombstones are hidden from every read by one listener, not by forty
   filters.** `register_tombstone_filter` attaches `with_loader_criteria` to
   `do_orm_execute`, which reaches relationship lazy loads that a hand-written
   `deleted_at IS NULL` could not - there is no line of code there to edit. The
   pull endpoint asks for them with `execution_options(include_tombstones=True)`.

5. **A revision belongs to a transaction.** `next_rev` claims one number per
   account per transaction and releases it on commit. The claim is a single
   `UPDATE ... RETURNING`: across Gunicorn workers, read-then-write hands the
   same number out twice.

6. **`uq_project_day_slot` is a partial unique index**, counting only rows where
   `deleted_at IS NULL`. Without that, freeing a slot would leave it permanently
   unbookable.

7. **A push parks bookings that are changing places.** Two bookings swapping
   arrive as two updates; applied one at a time the first lands where the second
   has not left yet. `_park_moving_bookings` marks them deleted for the length of
   two statements, and a sweep afterwards still refuses two rows that genuinely
   want one spot.

8. **After a push, the client records the revision the server assigned.** Without
   it the local row keeps the revision it was created with, and the next edit is
   sent against a version the server has already moved past - a conflict with
   nobody on the other side of it.

9. **A tag is not stored anywhere.** `#shop` is text inside `long_goal`.
   `frontend/src/domain/tags.ts` reads the plans and groups what it finds. A tag
   starts with a letter, may not follow a word character or `(`, and only counts
   inside a list item. The JavaScript pattern uses `\p{L}` rather than `\w`,
   which in JavaScript is ASCII and would cut `#dom-i-ogród` short.

10. **The health score is a convention, not a measurement.** `systemHealth` in
    `frontend/src/domain/slots.ts` mixes the done-ratio over the seven days *before
    today* with the share of active projects having a next session, weighted
    60/40, banded at 75 and 50. Today is deliberately outside the window.

11. **A day off moves bookings newest first.** Each lands on the date the one
    after it has just vacated. A session already marked done does not move - it
    happened - and holds back whatever would land on it.

12. **`is_private` is a curtain, not a permission.** Safe mode is browser-side,
    as it always was. The difference now is that the text it covers really is on
    this device rather than sent by a server.

13. **Signing out deletes the local copy.** It has to: the data is no longer
    only within a cookie's reach.

## What not to touch (and why)

- **The raw `ALTER TABLE` in `initialize_database`** - backward compatibility for
  old local databases. Change the schema with a migration.
- **The startup bootstrap and `SKIP_DB_BOOTSTRAP`** - deliberately disabled in
  Docker so workers don't race.
- **`OPENAI_API_KEY` and the `requests` package** - present but unused. Don't
  build on them; don't remove them without asking the repo owner.
- **Naive UTC in the database.** The client converts at the edges; the server
  stores instants and nothing else.
