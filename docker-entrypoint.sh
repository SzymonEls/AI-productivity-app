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
fi

flask --app run.py db upgrade
exec "$@"
