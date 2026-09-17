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
| [app/projects/slots.py](../app/projects/slots.py) | Daily A/B/C slots: date arithmetic, the two-block rule, the fortnight-long planner window, the calendar forwards (a month, on the schedule page) and backwards (three weeks a page, in the archive), moving a booking between blocks, taking a day off (pushing every booking from a day on one day later), counting how often a session has been put off, marking a booked block's session done on any day (the archive ticks past ones off) and the home page's health score. |
| [app/projects/day_notes.py](../app/projects/day_notes.py) | The other half of a day sheet: the list of notes under its three blocks. Reading a page's notes in one query, adding, rewriting and removing one, and moving a day's notes along with its bookings when a day is taken off. |
| [app/integrations/](../app/integrations/) | Subscribed calendars: the Integrations page (`routes.py`), fetching and caching an iCal URL (`feeds.py`) and reading the .ics itself (`ical.py`). One way only - the app never writes to a calendar. |
| [app/inbox/](../app/inbox/) | The inbox: capturing a thought before a project has been chosen for it, and filing one into a project's thoughts. Also the page behind the PWA shortcut, whose job is to raise the notification the service worker answers - see point 19. |
| [app/api/](../app/api/) | Token-authenticated JSON API (`/api/v1`) for the macOS menu bar client: today's slots, and starting/stopping a timer. |
| [app/auth/](../app/auth/) | Registration, login, logout, password change, issuing the API token. |
| [app/main/](../app/main/) | Home page (today's A/B/C slots, unscheduled projects, health score, the inbox widget) + PWA files (manifest, service worker). |
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

- **User** — username, email (both unique), hashed password. `session_token` is half of what the
  cookies carry, so a password change invalidates them; `api_token` is the separate bearer
  credential for `/api/v1`, which a password change deliberately leaves alone.
  `calendar_refresh_minutes` is how stale a subscribed calendar may get before the schedule
  re-reads it — a taste rather than a deployment setting, so it lives here and is set on the
  Integrations page, clamped to 5…1440 both where it is saved and where it is read.
- **Project** — `title`, `short_goal`, `frequency`, `long_goal` (Markdown), `archived_long_goal`,
  the flags `is_starred`/`is_private`/`is_archived`. `is_archived` takes a project out of the
  planning without touching its bookings — see point 15. `is_private` is a curtain, not a permission:
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
  `postponed_count` is how often the session has been pushed onto a later day, which is what
  colours its block on the schedule - see point 18.
  Unique on `(user_id, slot_date, slot)`, so a slot never holds two projects. Unlike
  `ProjectTimeEntry` it **does** cascade from `Project`: a slot left by a deleted project is an
  empty booking, not history. The rule "one slot today plus one in the future" is enforced in
  [app/projects/slots.py](../app/projects/slots.py), not by the schema.

- **DayNote** — one line of notes against one day (`note_date`, `body`, at most
  `DAY_NOTE_MAX_LENGTH` characters). Nothing unique about it: a day takes as many as get written,
  and their order is the order they were written in. It belongs to the user and the date, never to
  a project, so no project deletion cascades it away — see point 16.

- **InboxItem** — one thought captured before it was decided where it belongs: a `body` and
  nothing else. It has no `project_id`, and that absence *is* the state - an item exists precisely
  for as long as no project has been chosen for it. Filing one appends its text to that project's
  `short_goal` and deletes the row in the same transaction, so the inbox is a queue rather than a
  second copy of anything. Like a DayNote it is the user's, never a project's, so no project
  deletion cascades one away; unlike a DayNote it belongs to no date either, because when a
  thought was had says nothing about where it goes. See point 19.

- **CalendarFeed** — one subscribed iCal URL, plus the last copy of it that was read
  (`cached_ics`) and when. `checked_at` is every attempt, `fetched_at` only the ones that worked:
  the first keeps a dead URL from being retried on every page render, the second is what the page
  means by "last read". Events are not stored — see point 17.

The schema in the code matches the latest migration (`20260917_0026`).

## Responsibility boundaries

- **Business logic and database access live inside the `routes.py` functions.** There is no separate service/repository layer.
- **The exceptions are date arithmetic:** time and timezone calculations in
  [app/time_tracking/service.py](../app/time_tracking/service.py), and the two day-keyed modules
  that build on them — [app/projects/slots.py](../app/projects/slots.py) (the A/B/C blocks) and
  [app/projects/day_notes.py](../app/projects/day_notes.py) (the notes under them), both of which
  are shared by the schedule page, the archive and the home page rather than belonging to one view.
- **Talking to anything outside the process** is likewise kept out of the views:
  [app/integrations/feeds.py](../app/integrations/feeds.py) fetches, and
  [app/integrations/ical.py](../app/integrations/ical.py) parses, so
  [app/integrations/routes.py](../app/integrations/routes.py) is forms and flashes like any other
  page.
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

    The day's **notes travel with it**, in `shift_notes_forward`
    ([app/projects/day_notes.py](../app/projects/day_notes.py)), called by the same endpoint. That
    one is a plain date change: a note has no "done" to stay behind for and no slot to collide
    over, so nothing holds one back and nothing needs flushing row by row.

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
    ([app/projects/slots.py](../app/projects/slots.py)) is one ratio — how many of the sessions
    booked over the 7 days **before today** were marked done (A, B and C alike; an unfilled slot
    counts on neither side of it) — with the bands at 75 and 50 deciding the colour. The window and
    those two numbers are constants at the top of the file; change them there, not in the template.
    Two consequences worth knowing: today is deliberately outside the window, so the score moves in
    the morning only when yesterday was left unfinished, and a week with nothing booked scores zero
    rather than dividing by zero.

    **Planning is reported, not scored.** Whether every active project has a next session booked
    comes back from the same call (`planning_ok` and the counts beside it) and the home page shows it
    as a second, smaller ring beside the score: green with a check when every project is booked ahead, amber with a cross when some are not. It used to be 40% of the number, which was wrong twice
    over: having booked ahead is the baseline rather than an achievement, and because it is normally
    complete it put a permanent floor under the score that no amount of missed sessions could break
    through. Read the other way round it is the "Not scheduled" list on the same page, so the two
    always agree.

13. **The API answers a click, the web page answers a form — so their `start` rules differ.**
    `POST /time-tracking/projects/<id>/start` refuses with a 409 while another project's timer
    runs, because the web page has room to say so and a Stop button to press. The menu bar has
    neither: one click means "this is what I am on now", so `POST /api/v1/timer/start`
    ([app/api/routes.py](../app/api/routes.py)) stops whatever was running and reports it back as
    `stopped`. Two rules on purpose, not an oversight — keep them apart.
14. **`/api/v1` is unreachable with a cookie, and the pages are unreachable with a token.**
    The API uses `_token_required` rather than `@login_required`, which would redirect a desktop
    client to an HTML login page it can only read as a confusing 200. Nothing in `app/api/`
    touches `current_user`; the authenticated user is put on `g.api_user` instead.
15. **Archiving a project is about planning, not about hiding it.** `is_archived` takes the
    project out of every surface that exists to *fill a block* — the "Not scheduled" list and the
    health count on the home page, the picker behind an empty block on the schedule, the timeline,
    the tag search, the project switcher — and `assign_slot`
    ([app/projects/slots.py](../app/projects/slots.py)) refuses it a slot outright, which is why the
    project page drops its "Plan next session" button rather than opening a dialog that can only say
    no. What it deliberately does **not** do is touch `project_day_slots`: a session already booked
    still stands, still shows on the schedule board and the home page, can still be moved, freed or
    ticked off, and still counts towards the health score. That is the whole point — you archive
    something you have stopped taking on, not something you have stopped doing this week.

    One exception follows from it, in `build_project_switcher_context`
    ([app/__init__.py](../app/__init__.py)): an archived project **sitting in a slot today** is back
    in ⌘K, under "Today" and tagged `archived`. It is today's work, so it has to be reachable; it
    still stays out of the list of everything else underneath. The switcher reads today's slots
    first for exactly this reason — which projects to make an exception for is read off them — and
    is still two queries.

16. **A day sheet's notes are live in the archive, and the blocks above them are not.** The same
    macro draws both pages ([app/templates/projects/_day_sheet.html](../app/templates/projects/_day_sheet.html));
    `readonly=True` drops every control that would change a booking, because nothing about a day
    that has been can still be planned. It deliberately leaves two things alone: the ✓ on a booked
    block, and the note list under it. Both describe what a day *was* rather than what is planned
    for it, and both are usually filled in afterwards — so `add_day_note` takes any date without
    asking where it falls, and one script
    ([app/static/js/day-notes.js](../app/static/js/day-notes.js)) serves the board and the archive.
    A note is also the one thing on a sheet that outlives the project it was written about: it has
    no `project_id`, so deleting a project takes its bookings and leaves the notes.

    The line itself is the control that rewrites it — a `<button>` styled back down to plain text,
    swapped for an input in place. Enter and clicking away keep what was typed; **Escape puts the
    line back, and an emptied line is left as it was**, because clearing the text by accident is
    not the same gesture as reaching for the ×, and only one of the two is meant to lose it.

17. **A subscribed calendar is cached whole and expanded per page.** There is no such thing as
    asking an iCal URL for a date range — the file is the whole calendar or nothing — so
    `fetch_feed` takes all of it (capped at `MAX_FEED_BYTES`) and `CalendarFeed.cached_ics` holds
    it exactly as it arrived. `events_by_day` ([app/integrations/ical.py](../app/integrations/ical.py))
    then works out the occurrences **for the days the page is showing**, every time it renders: the
    download is everything, the expansion is the window. Storing events instead would mean deciding
    how far ahead to expand a weekly meeting that repeats forever, and re-deciding it whenever the
    window grew; parsing a few hundred lines is cheaper than that, and it means a feed that stops
    answering keeps showing the calendar it last knew about instead of emptying the sheets.

    **The expansion is cached per version of the calendar** (`_expanded` in
    [feeds.py](../app/integrations/feeds.py)), keyed on the feed, its `fetched_at`, the window and
    the timezone, and bounded at `MAX_CACHED_WINDOWS`. Without it the same text was re-parsed on
    every render, which is most of what a schedule page costs once there are calendars on it:

    | calendars (407 events each) | render, uncached | render, cached |
    |---|---|---|
    | none | 3.6 ms | 3.6 ms |
    | 1 | 12.5 ms | 4.0 ms |
    | 3 | 30.5 ms | 4.5 ms |
    | 10 (the maximum) | 93.6 ms | 6.6 ms |

    A re-read changes `fetched_at`, so the first render after one pays the ~90 ms again and the
    rest come off the cache — and that first one is the background refresh request, not a page
    anybody is waiting on. Nothing is invalidated by hand; old keys age out.

    Inside that, a recurring event is **walked from its own DTSTART**, not from the window: `COUNT`
    is an ordinal, and an occurrence is only the fifth if the four before it were worked out too.
    Everything before the window is counted and dropped. The two limits that bound the walk are
    therefore different numbers and must stay that way — `MAX_OCCURRENCES` is how many occurrences
    a page may be handed, `MAX_STEPS` is how far the walk may travel to reach them. Conflating them
    is a real bug this code has already had: a daily meeting standing since 2019 is 2,800 rounds
    from this week, the walk stopped at 2,000, and the event silently vanished from every sheet.

    **Nothing is fetched while a page renders.** There is no scheduler in this app, so the
    schedule page is still what drives the reading — but it does it *after* it is on the screen,
    not in the render someone is waiting on. The render asks `has_stale_feeds` (one count, no
    network) and, if anything is due, carries `[data-calendar-refresh]` with the days it is
    showing; [calendar-feeds.js](../app/static/js/calendar-feeds.js) then posts to
    `/integrations/calendars/refresh-due`, which runs `refresh_due` and answers with the events
    for those days, and the page patches in whatever came back different. A stale calendar on a
    host that takes three seconds to answer costs a 13 ms render and a request nobody is watching,
    where doing it inline cost three seconds of blank screen.

    While that round runs, the page shows a spinner in its top right — not a request for
    patience, since the page is already complete, but the honest statement that the event lines
    may still change underneath. It is the only thing the reader sees of any of this.

    The safeguards behind that are still worth keeping: a feed is only re-read once the user's own
    `calendar_refresh_minutes` have passed, a failed read counts as a read for that purpose (so a
    dead URL is retried on that interval rather than on every page), and a round is bounded by
    `REFRESH_BUDGET_SECONDS`, with whatever is left over staying due for next time. The two
    fetches that *are* synchronous are both ones a person asked for and is watching: adding a
    calendar, and "Read them now".

    With JavaScript off, a calendar is read when it is added and when that button is pressed, and
    not otherwise. That is the trade: the alternative was every reader occasionally paying for it.

    The URL is fetched by the server, so `add_feed` refuses one whose host resolves to a private
    or loopback address: registration can be open, and without that check the app would be an
    open proxy into whatever network it is deployed in.

18. **A session's colour is counted, not worked out.** `postponed_count` on `ProjectDaySlot` is a
    running tally kept by `move_booking` and `shift_bookings_forward`
    ([app/projects/slots.py](../app/projects/slots.py)), not something derived from the dates: a
    booking's history is a single row that gets updated, so by the time it sits on a later day
    there is nothing left to compare it with.

    `postponement_after` is the whole rule. Landing on a later day is one step on, an earlier day
    one step back, and a move inside one sheet — A to B on the same date — is not a move in time
    and counts nothing. **Nothing caps it on the way up**, and that is deliberate: a session pushed
    four times has to be pulled back four times to come off red, because anything else would let
    four postponements be undone by one and the block would go quiet while the plan was still three
    days behind. The floor at zero is the one bound.

    **`MAX_POSTPONED_LEVEL` (2) caps the colour, not the count.** `postponed_level()` is the whole
    of that: 0, 1 or 2, and the class rendered is the level, so the stylesheet always has a colour
    for it however high the count has run. Past two the extra moves are invisible on the block and
    readable in the tooltip, which says the number — that is where "four times" and "twice", which
    look identical, differ.

    A swap moves both bookings, in opposite directions, and the displaced row is rebuilt only to
    get past the unique constraint, so its count is carried across by hand — it was moved, not
    rebooked.

    A day off counts for every booking it moves, and nothing for one it holds back (see point 10).
    Freeing the block throws the tally away with the row: booking the project again is a new plan,
    and a new plan starts from nothing being late. This is the reason the count lives on the
    booking rather than on the project.

    The board applies a move to the page before the server has answered, so `refreshCell` in
    [app/static/js/schedule-board.js](../app/static/js/schedule-board.js) keeps its own copy of the
    same arithmetic, and the count rides on `[data-slot-content]` — the element that travels — the
    way `data-done` does, even though it is the block around it that gets tinted.

    The tint is backed by a **`!`** between the title and the block's buttons, because a colour on
    its own is not something every reader can tell apart; it takes the block's own accent rather
    than a third colour, and it carries the tooltip. It is not rendered on a finished session — the
    block is green by then and nothing about it is late. Being a sibling of the content rather than
    part of it, it does **not** travel on a move, so `refreshCell` redraws it and `moveContentInto`
    anchors on the letter instead of on the `×`: inserting before the `×` would drop the content
    behind a `!` the block has not shed yet.

19. **A thought is captured by the service worker, not by a page.** The inbox exists because
    capturing and filing are two different moments: on a phone you have a sentence and no
    patience for picking a project, at the desk you have the list in front of you. So an item
    arrives with nothing but its text and waits on the home page until a project is chosen.

    The capture path is the unusual part. `manifest.webmanifest` declares a `shortcuts` entry,
    which Android puts in the menu behind a long press on the installed app's icon; it opens
    `/inbox/capture`, whose only real job is to call `showNotification` with an action of
    `type: "text"` and then be irrelevant. The reply is delivered to the **`notificationclick`
    handler in [service-worker.js](../app/static/service-worker.js)**, which posts it to
    `/inbox` with `credentials: "include"` and re-shows the notification. A service worker is
    woken for that event whether or not a window is open, so the whole round trip happens with
    the app never really launching - you stay in whatever you were doing, pull the shade down,
    tap Add, dictate, send.

    Three consequences worth knowing:

    - **The endpoint is cookie-authenticated, not `/api/v1`.** The service worker already has the
      session cookie and a token would have to be stored somewhere; it asks with
      `X-Requested-With`, so an expired session comes back as the JSON 401 from
      `register_login_handlers` rather than as a login page the worker would read as a success.
      This is the one write path in the app that runs with no window open, which is exactly why
      it reuses the browser's own credential rather than inventing a second one.
    - **A reply field cannot be pre-filled**, so a failed save quotes the text back in the
      notification body and makes it sticky. That is all that is left of it - there is no retry
      queue, and adding one would mean a store the worker can reach.
    - **Notifications do not survive a reboot.** The shortcut re-creates the notification, so the
      recovery is to use the shortcut again; nothing is lost, but the shade is empty until you do.
      `inbox-capture.js` also keeps a plain textarea on that page for the devices that refuse
      notifications outright, which is the same box the + beside "Today" opens.

    Filing is the ordinary half: the picker on the home page posts to `/inbox/<id>/file`, which
    appends the text to `Project.short_goal` behind a blank line and deletes the row in one
    transaction. It stays plain text - no date stamp, no bullet - because `short_goal` has no
    structure to respect and inventing one would only have to be parsed back out later. The
    widget is rendered `hidden` rather than omitted when the inbox is empty: the + has to be able
    to fill it without a reload, and the row markup and project list it clones come from the
    `<template>` that section carries.

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
