# Local-first sync — the record of the 2.0.0 rewrite

What was decided, what went wrong, and what has actually been verified. The
architecture as it now stands is in [ARCHITECTURE.md](ARCHITECTURE.md); this
file is the reasoning behind it and the traps found on the way.

Branch `se/local-first-sync`, 39 commits, `VERSION` 2.0.0.
123 files changed: +14 128 / −10 093. Server 2 805 lines of Python, client
9 217 lines of TypeScript and Svelte. 132 tests (37 server, 95 client).

---

## What changed, in one paragraph

The application used to render every page on the server. It now keeps a copy of
your data in the browser and draws everything from that; the server
authenticates, stores the shared copy, and answers two questions — what changed
since a given point, and here is what I changed, what of it can you take. The
whole application works with the network off, and the button in the top right
says what is waiting.

## Decisions taken with the owner

| Decision | Choice |
|---|---|
| Role of the server | Sync API + shell; the Jinja pages are gone |
| Frontend tooling | npm + Vite + TypeScript, Svelte 5 |
| Conflicts | Always ask the person — nothing is merged silently |
| Sync mode | Automatic when online; the button is the visible state and "Sync now" |
| Deletions | Content wiped at once, the empty row kept 90 days, then really deleted |
| `PRAGMA secure_delete` | On |
| Where the client is built | On the server, as the deploy already worked |

Two things the owner asked for that changed the plan mid-way: the phased
"run both interfaces for weeks" rollout was dropped, and the interface had to
match the old one exactly rather than being a fresh design.

---

## The three things that made synchronisation possible

Every one of these is a column that a plain autoincrement primary key cannot
stand in for. Migration `20260901_0021` adds all three.

**`uid`** — a ULID minted by whoever creates the row. A browser with no network
cannot wait for SQLite to hand out a key, and two devices inventing the same
integer would silently merge two different projects. The integer id stays where
it was; `uid` lives beside it and is the only identity the protocol speaks.

**`rev`** — a per-account counter stamped by the server. An ordering, not a
clock: two devices disagree about the time but not about which change came
second. It makes "everything above my cursor" an exact question and a conflict
detectable at all.

**`deleted_at`** — a tombstone. A row that simply vanished is indistinguishable
from one that never changed, so the other device would never learn of the
deletion and would push its own copy back.

---

## Bugs found, and how

The ones worth remembering, because most were not findable by reading.

### The migration made existing data invisible

Rows were backfilled with `rev = 0`, and a first sync asks for everything above
cursor 0. An account with years of projects would have looked empty to a new
device. **Found by running the app against real data**, not by any test — the
test database starts empty, so nothing was there to be invisible.
`tests/test_migration_0021.py` exists for this: it migrates a database that
already holds rows.

### Stopping a timer raised a conflict with nobody

After a push the client did not record the revision the server assigned, so the
local row kept the revision it was created with and the very next edit was sent
against a version the server had already moved past. **Found by clicking start
and then stop.** Fixed in `sync/engine.ts`; regression test in
`sync/engine.test.ts`.

### Two bookings swapping places crashed the server

A swap arrives as two updates. Applied one at a time, the first lands where the
second has not left yet, and the partial unique index refuses it — a 500. The
Jinja `move_booking` had always worked around this; the push endpoint had not.
`_park_moving_bookings` now marks the moving rows deleted for the length of two
statements, and a sweep afterwards still refuses two rows that genuinely want
one spot (as a 409, not a 500).

### Milliseconds lost in the time-zone offset

`Intl.DateTimeFormat.formatToParts` stops at seconds, so the computed offset was
short by a fraction and the end of a day landed after midnight. **Found by the
golden file** generated from the Python this replaced — an assumption-free
comparison is the only reason this surfaced.

### The empty-block overlay covered a booking

The absolutely-positioned `.day-slot-fill` button was rendered over booked
blocks as well, so the pointer never reached the draggable element and native
dragging could not start. In the original the overlay carries `d-none` on a
booked block for exactly this reason. **Reported by the owner**, twice, before
being found — the first attempt fixed the wrong thing.

### A revision belonged to the wrong lifetime

`next_rev` memoised on `g`, the app context. In production that is one request,
but a test holds one context across many, so every request got the same number.
The real fix was conceptual: a revision belongs to a **transaction**, and is
released on commit or rollback.

---

## Where the interface diverged, and why it mattered

The rewrite was checked control by control against `main` running side by side
on another port. What follows was invented rather than ported, and had to be
undone:

- A **tick on the home slot card** — the original has none. A session is
  finished on its project's page or on a sheet in the schedule.
- **"Star project" / "Make public"** as menu items — both flags live in the
  project settings dialog.
- A **`⇄` grip** to move a booking, added on the theory that HTML5 drag does not
  work on touch. The original had already solved that: clicking anywhere on a
  booked block picks it up, and the title link is suppressed on the board
  because *"on the board a click means move this, not open it"*.
- **Seven navigation links** where the original has four; Tags, Archive and
  "new project" are reached from the pages that own them.
- **`planner-projects` / `planner-project`** class names that do not exist. The
  picker is `picker-list` / `picker-row`.
- **Archive paging by a fixed three weeks from the cursor**. The original steps
  from the page's own edge (`first_day - 1`), which is what keeps pages gapless
  whatever weekday the first one starts on. Now in `archivePaging()` with tests.
- An **"Edit" toggle over the plan**. In blocks mode — the default — the editor
  *is* the view: always editable, saving itself, reporting "All changes saved".
- **One "Details" card** instead of three (Thoughts / Frequency / Daily target),
  each with its own inline Edit.
- **Lucide icons** where the original uses FontAwesome. The exact classes matter:
  `fa-regular fa-clock`, `fa-regular fa-circle-check`, `fa-solid fa-ellipsis`
  and the rest.

Two divergences were kept deliberately: the **sync button** in the navbar is new
by design, and time tracking has **no "Show" button** because the filters read
from the local copy and there is nothing to submit.

### The lesson

The stylesheet was the best test available. `styles.css` was written for the
server's HTML; when the ported Markdown renderer produced the same class names,
the coloured section cards and the step rail fitted **without one line of new
CSS**. That is stronger evidence the port is faithful than the golden files are.

---

## What is verified, and what is not

Every write below was confirmed by reading the row back out of SQLite after
clicking it in the browser.

**Verified:** booking, moving (tap and drag), swapping, freeing a slot, taking a
day off, ticking a session off from the project and from the archive, the
session planner from both entry points, the block editor's autosave and its
section archive/restore round trip, project create/edit/archive/delete, the
timeline's edit mode with group and card moves, tags, time tracking filters and
row edits, the timer modal, conflict detection and resolution, signing in and
out (including that signing out deletes the local copy), the theme, safe mode,
⌘K and the settings dialog.

**Not verified, and it should be:**

- **The service worker.** The file is served correctly — 200, right content
  type, `Service-Worker-Allowed` — but registration fails in the automation
  browser, so offline loading of the *shell* is untested. Offline reading of the
  *data* is verified.
- **The two-stage Docker build.** Docker was unavailable. The paths were worked
  through (`vite` writes to `/app/static/client`, `COPY --from` takes it) but the
  first deploy has to prove it. Measure the Node stage's peak memory then: it
  runs on the deployment host, beside the container it is replacing.
- **Native mouse dragging on the schedule.** Everything checkable was checked —
  nothing covers the draggable element, `pointer-events: auto`,
  `-webkit-user-drag: element`, `dragstart` reaches the handler, and the full
  `dragstart → dragover → drop` sequence moves the booking. The automation tool
  cannot produce native drag events, so a human still has to try it.

---

## Traps for whoever works on this next

**The protocol is written twice.** `app/api/protocol.py` and
`client/src/sync/types.ts` describe the same tables. They drifting apart is what
this codebase is most exposed to; the checklist says to change both.

**Never `db.session.delete` a synchronised row.** Use `soft_delete`, which also
empties the content columns listed in `__sync_payload__`. Time entries are the
one exception to the cascade: they outlive their project holding
`project_title_snapshot`, so past weeks stay readable.

**Never set `rev` by hand.** A `before_flush` listener stamps every write, so no
route has to remember.

**Tombstones are hidden by one listener, not by filters.** `with_loader_criteria`
on `do_orm_execute` reaches relationship lazy loads, which a hand-written
`deleted_at IS NULL` cannot — there is no line of code at
`project.day_slots` to edit. The pull endpoint opts back in with
`execution_options(include_tombstones=True)`.

**A golden file is worth more than an assumption.** Regenerate
`client/src/domain/__golden__*.json` from the Python rather than editing them.

**Run both suites**: `pytest` and `cd client && npm run test`.

---

## Running it

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

```bash
cd client && npm install && npm run build && cd ..
```

```bash
python run.py
```

There is no Node process in production; `npm run build` writes static files that
Flask serves. `npm run dev` in `client/` gives hot reload on port 5173 and
proxies the API to Flask — run `python run.py` alongside it.

To compare against the old interface, a worktree of `main` on another port is
the way it was done here:

```bash
git worktree add /tmp/main-app main && cp demo/example/app.db /tmp/main.db
```

---

## Still open

- **Undoing a deletion** on the client — a "Undo" window before the operation
  leaves the outbox. Deliberately out of scope; there is no server-side bin.
- **`GET /api/export`** is the only route to the data if the client ever breaks.
  It exists; it is worth keeping that way.
- **Two undeclared indexes** on `project_time_entries` were declared on the model
  so `flask db check` passes. That drift had been open since migration
  `20260808_0016`.
