# Deploying the read-only demo

How to put a public, look-but-don't-touch copy of the app on the same server that already
runs the private instance. Behaviour of demo mode itself is described in
[ARCHITECTURE.md](ARCHITECTURE.md), the "Demo mode" section.

The demo runs from the **same image** as the private instance; only the environment differs.
Nothing in this guide touches [docker-compose.yml](../docker-compose.yml) or `app/instance/`.

## 1. Tag the release

[docker-compose.demo.yml](../docker-compose.demo.yml) builds from the repository at a pinned
tag, the same way the private instance does. Push the tag before deploying:

```bash
git tag v1.5.0 && git push origin v1.5.0
```

## 2. Start the container

On the server, in the directory that holds the compose files:

```bash
docker compose -f docker-compose.demo.yml up -d --build
```

What happens on first boot ([docker-entrypoint.sh](../docker-entrypoint.sh)):

1. `./demo-instance/.env` is created with a freshly generated `SECRET_KEY` — a different one
   from the private instance.
2. `flask db upgrade` builds the schema in `./demo-instance/app.db`.
3. `flask seed-demo` fills it with sample projects, a timeline, two weeks of tracked time and
   a daily plan.

Step 3 is idempotent, so restarts and redeploys leave the demo database alone. To rebuild it:

```bash
docker compose -f docker-compose.demo.yml exec web flask --app run.py seed-demo --reset
```

Check it answers before wiring up nginx:

```bash
curl -sI http://127.0.0.1:8010/auth/login | head -1
```

## 3. Point nginx at it

The container publishes port `8010` on the host (`DEMO_APP_PORT` overrides it). A server block
for the demo subdomain:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name demo.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name demo.example.com;

    ssl_certificate     /etc/letsencrypt/live/demo.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/demo.example.com/privkey.pem;

    # The demo account is public, so keep login attempts from becoming a nuisance.
    limit_req_zone $binary_remote_addr zone=demo_login:10m rate=10r/m;

    location /auth/login {
        limit_req zone=demo_login burst=10 nodelay;

        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`limit_req_zone` belongs in the `http` block on some setups; move it out of `server` if nginx
complains. Then:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Get the certificate with `sudo certbot --nginx -d demo.example.com` if you do not have one yet.

## 4. Check it from outside

Open `https://demo.example.com/` in a private window and confirm:

- the login form arrives pre-filled and there is no link to register;
- the document from `DEMO_DOC_PATH` is rendered below the form;
- the "Demo" banner is visible on every page after logging in;
- dragging a card on the timeline, starting the timer, or saving a project all report
  "Demo mode - changes are disabled." and change nothing after a refresh.

## Notes

- **Never set `DEMO_MODE=0` on the public container.** The app has no CSRF protection, which is
  harmless only because every write is refused.
- The demo password is public by design. The account holds nothing but seeded content, and
  changing the password is a POST, so it is blocked like everything else.
- To show a page written for visitors instead of the developer-facing `README.md`, add your own
  Markdown file and set `DEMO_DOC_PATH` to it. Relative links inside the document are rewritten
  to `DEMO_DOC_BASE_URL` so they resolve to the repository on GitHub.
