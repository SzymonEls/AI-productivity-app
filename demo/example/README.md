# Example demo database

`app.db` is a ready-made SQLite database for the read-only demo: one account, six projects
covering every flag the UI can show, today's A/B/C slots plus two future sessions, a timeline
with a backlog group and a note, two weeks of tracked work sessions, and a saved daily plan.

| | |
|---|---|
| Email | `demo@example.com` |
| Password | `demo` |
| Schema | at migration `20260808_0016` |

It is a convenience copy, not the source of truth: it was produced by
`flask --app run.py seed-demo`, and that command is what a deployed demo runs on first boot
([docker-entrypoint.sh](../../docker-entrypoint.sh)). Regenerate it rather than editing it.

## Using it

Drop it in and start the app with demo mode on:

```bash
cp demo/example/app.db app/instance/app.db
```

```bash
DEMO_MODE=1 DEFAULT_LOGIN_EMAIL=demo@example.com DEFAULT_LOGIN_PASSWORD=demo REGISTRATION_ENABLED=false flask --app run.py run
```

## Rebuilding it

```bash
rm -f demo/example/app.db && DEMO_MODE=1 DEFAULT_LOGIN_EMAIL=demo@example.com DEFAULT_LOGIN_PASSWORD=demo DATABASE_URL=sqlite:///demo/example/app.db flask --app run.py seed-demo
```

## This file goes stale, and the day slots make that obvious

Everything dated is seeded relative to the moment the file is built. Work sessions merely thin
out as it ages, but **the day slots are worse**: the day after this file is built, its "today"
slots are in the past, and the dashboard — the first screen a visitor sees — shows three empty
slots. Rebuild it on the day you deploy.

A deployed demo starts out fine, because the entrypoint seeds it on first boot. It does **not**
stay fine: `seed-demo` is idempotent, so restarts never refresh the dates. A demo left running
for a week shows an empty dashboard too. Re-seed it on a schedule, for example daily:

```bash
docker compose exec web flask --app run.py seed-demo --reset
```

The password here is public on purpose. The account holds nothing but the content above, and in
demo mode every write, including changing the password, is refused.
