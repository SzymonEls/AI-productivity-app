#!/bin/sh
set -eu

export SKIP_DB_BOOTSTRAP="${SKIP_DB_BOOTSTRAP:-1}"

flask --app run.py db upgrade

exec "$@"
