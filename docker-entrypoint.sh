#!/bin/sh
set -eu

export SKIP_DB_BOOTSTRAP="${SKIP_DB_BOOTSTRAP:-1}"

# The repository root is /app, so config.py reads /app/app/instance/.env. Writing
# anywhere else produces a file the application never looks at.
INSTANCE_DIR="/app/app/instance"
ENV_FILE="${INSTANCE_DIR}/.env"

mkdir -p "$INSTANCE_DIR"

if [ ! -f "$ENV_FILE" ]; then
    SECRET_KEY="${SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(48))')}"
    DATABASE_URL="${DATABASE_URL:-sqlite:////app/app/instance/app.db}"
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

# A migration that rewrites every row has no way back: SQLite rebuilds the whole
# table (create, copy, drop, rename), so an interrupted upgrade can leave the file
# half converted, and "db downgrade" drops columns rather than restoring content.
# The copy costs a few megabytes and is the only thing standing between a failed
# deploy and lost data. Keeping the last few is enough - they are ordered by name.
DB_FILE="$(python -c 'from config import Config; uri = Config.SQLALCHEMY_DATABASE_URI; print(uri[10:] if uri.startswith("sqlite:///") else "")')"
if [ -n "$DB_FILE" ] && [ -f "$DB_FILE" ]; then
    DB_REV="$(flask --app run.py db current 2>/dev/null | awk 'NF {rev = $1} END {print rev}')"
    cp "$DB_FILE" "${DB_FILE}.bak-${DB_REV:-unknown}-$(date +%Y%m%d-%H%M%S)"
    ls -1t "${DB_FILE}.bak-"* 2>/dev/null | tail -n +6 | while read -r stale; do
        rm -f "$stale"
    done
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
