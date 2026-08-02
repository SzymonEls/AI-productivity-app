#!/bin/sh
set -eu

export SKIP_DB_BOOTSTRAP="${SKIP_DB_BOOTSTRAP:-1}"
ENV_FILE="/app/instance/.env"

mkdir -p /app/instance

if [ ! -f "$ENV_FILE" ]; then
    SECRET_KEY="${SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(48))')}"
    DATABASE_URL="${DATABASE_URL:-sqlite:////app/instance/app.db}"
    REGISTRATION_ENABLED="${REGISTRATION_ENABLED:-true}"
    CALENDAR_TIMEZONE="${CALENDAR_TIMEZONE:-Europe/Warsaw}"
    OPENAI_API_KEY="${OPENAI_API_KEY:-}"

    cat > "$ENV_FILE" <<EOF
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=${DATABASE_URL}
REGISTRATION_ENABLED=${REGISTRATION_ENABLED}
CALENDAR_TIMEZONE=${CALENDAR_TIMEZONE}
OPENAI_API_KEY=${OPENAI_API_KEY}
EOF
elif ! grep -q '^SECRET_KEY=' "$ENV_FILE"; then
    # The file was written by hand (that is how a demo is configured), so it may
    # have no key. Without one the app would silently fall back to the shared
    # development default and every session cookie would be forgeable.
    python -c 'import secrets; print("SECRET_KEY=" + secrets.token_urlsafe(48))' >> "$ENV_FILE"
fi

flask --app run.py db upgrade

# Demo instances start with sample content. DEMO_MODE usually comes from the
# .env file above rather than the container environment, so ask the app itself
# instead of testing a shell variable. seed-demo is idempotent, so a restart
# never overwrites the demo database; pass --reset to rebuild it.
if python -c 'import sys; from config import Config; sys.exit(0 if Config.DEMO_MODE else 1)'; then
    flask --app run.py seed-demo
fi

exec "$@"
