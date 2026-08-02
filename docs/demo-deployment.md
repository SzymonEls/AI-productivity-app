# Deploying the read-only demo

How to put a public, look-but-don't-touch copy of the app on the same server that already runs
the private instance. What demo mode does is described in [ARCHITECTURE.md](ARCHITECTURE.md),
point 9 of "Non-obvious things".

There is **one** [docker-compose.yml](../docker-compose.yml) for both. An instance is a demo
because of what is in its `app/instance/.env`, not because of a different compose file. Two
instances are therefore two directories, each with its own database and its own settings.

## 0. Upgrading an instance built before 1.5.0

Older images mounted the instance directory at `/app/instance`, but `config.py` reads
`/app/app/instance` — the repository root is `/app`, so its `app/instance` is one level deeper.
The `.env` in that volume was therefore **never read**, and only the `environment:` block in
`docker-compose.yml` had any effect. The paths line up from 1.5.0 on.

Two consequences when you upgrade:

- **Settings in `app/instance/.env` become live for the first time.** If that file was generated
  by an older entrypoint it says `REGISTRATION_ENABLED=true`, which will now take effect. Read it
  before upgrading and set what you actually want.
- **The generated `SECRET_KEY` becomes live too**, so existing sessions are invalidated once —
  everyone signs in again. Until now the app silently used the built-in development key.

The database is unaffected: the same host file is simply mounted at the correct path.
Back it up anyway.

```bash
cp app/instance/app.db app/instance/app.db.bak
```

If the file also carries a `DATABASE_URL=sqlite:////app/instance/app.db` line from an old
deployment, delete it — that path is not mounted any more. The `environment:` block overrides it,
so nothing breaks while it is there.

## 1. Tag the release

Compose builds from the repository at a pinned tag. Push it before deploying:

```bash
git tag v1.5.0 && git push origin v1.5.0
```

## 2. Set up the demo directory

```bash
mkdir -p ~/demo/app/instance && cd ~/demo
curl -O https://raw.githubusercontent.com/SzymonEls/AI-productivity-app/v1.5.0/docker-compose.yml
```

Write `~/demo/app/instance/.env` — this file is what makes the instance a demo:

```ini
DEMO_MODE=true
REGISTRATION_ENABLED=false

# Pre-filled on the login page, so deliberately public.
DEFAULT_LOGIN_EMAIL=demo@example.com
DEFAULT_LOGIN_PASSWORD=demo

# Markdown rendered under the login form; relative links resolve against the repo.
DEMO_DOC_PATH=README.md

# Banner above every page. An empty value removes it.
DEMO_BANNER_MESSAGE=Read-only portfolio demo — nothing you change here is saved.
```

`SECRET_KEY` is deliberately absent: [docker-entrypoint.sh](../docker-entrypoint.sh) appends a
random one on first boot, so the demo never shares a key with the private instance. Every
setting is listed in [app/instance/.env.example](../app/instance/.env.example).

## 3. Start it

```bash
docker compose up -d --build
```

On first boot the entrypoint adds the `SECRET_KEY`, runs `flask db upgrade`, and — because
`DEMO_MODE` is on — runs `flask seed-demo`, which fills the database with sample projects, a
timeline, two weeks of tracked time and a daily plan. Seeding is idempotent, so restarts and
redeploys leave the demo database alone. To rebuild it:

```bash
docker compose exec web flask --app run.py seed-demo --reset
```

Nothing is published on the host. Check the container answers from inside the proxy network
before touching nginx (substitute your nginx container's name):

```bash
docker exec nginx curl -sI http://demo_web_1:8000/auth/login | head -1
```

`demo_web_1` is Compose's generated name: directory + service + index. Renaming or moving the
directory renames the container, and nginx then has to be updated to match.

## 4. Point nginx at it

Resolving the upstream through Docker's embedded DNS via a variable keeps nginx from refusing
to start while the demo container is down.

In the `http` block, next to the other zones:

```nginx
# The demo password is public, so keep login attempts from becoming a nuisance.
limit_req_zone $binary_remote_addr zone=demo_login:10m rate=10r/m;
```

Then the server block:

```nginx
server {
    listen 443 ssl;
    server_name demo.example.com;

    ssl_certificate     /etc/nginx/ssl/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/live/example.com/privkey.pem;

    resolver 127.0.0.11 valid=10s;

    set $upstream demo_web_1:8000;

    location /auth/login {
        limit_req zone=demo_login burst=10 nodelay;

        proxy_pass http://$upstream;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://$upstream;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
docker exec nginx nginx -t && docker exec nginx nginx -s reload
```

## 5. Check it from outside

Open `https://demo.example.com/` in a private window and confirm:

- `/` sends you straight to the login page, which arrives pre-filled and offers no registration;
- the document from `DEMO_DOC_PATH` is rendered below the form under "About the project";
- the banner is visible on every page after logging in;
- dragging a card on the timeline, starting the timer and saving a project all report
  "Demo mode - changes are disabled." and change nothing after a refresh.

## Notes

- **Never point a public URL at an instance with `DEMO_MODE` off.** The app has no CSRF
  protection, which is harmless only because every write is refused.
- The demo password is public by design. The account holds nothing but seeded content, and
  changing the password is a POST, so it is blocked like everything else.
- Keep the two directories apart. Running the demo from the private instance's directory would
  mount the private `app/instance` and put real data on a public URL — read-only, but visible.
- A ready-made database is in [demo/example/](../demo/example) if you would rather copy one in
  than seed on the server.
