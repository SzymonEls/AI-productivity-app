# Example demo database

`app.db` is a ready-made SQLite database for the read-only demo: one account, six projects
covering every flag the UI can show, a timeline with a backlog group and a note, two weeks of
tracked work sessions, and a saved daily plan.

| | |
|---|---|
| Email | `demo@example.com` |
| Password | `demo` |
| Schema | at migration `20260705_0015` |

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

Do this after a schema migration, and whenever the tracked-time charts start looking empty:
work sessions are seeded relative to the moment the file is built, so they drift into the past
as the file ages. A deployed demo does not have this problem — it seeds itself at startup.

The password here is public on purpose. The account holds nothing but the content above, and in
demo mode every write, including changing the password, is refused.
