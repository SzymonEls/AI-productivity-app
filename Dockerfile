# The client is built here and only its output is carried forward, so Node
# never reaches the image that runs in production.
FROM node:26-slim AS client

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# A hard ceiling rather than growing until the machine runs out: the build
# happens on the deployment host, alongside the container it is replacing.
ENV NODE_OPTIONS=--max-old-space-size=512
RUN npm run build


FROM python:3.13-slim

ARG APP_UID=1000
ARG APP_GID=1000

ENV FLASK_APP=run.py \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# vite.config.ts writes into the backend's static folder; the directory is
# git-ignored, so it arrives only from the stage above.
COPY --from=client /backend/app/static/client ./backend/app/static/client

# The repository root is /app, so the instance directory - where config.py
# reads .env and the database from - is /app/instance. Keep the volume, the
# entrypoint and DATABASE_URL pointed at the same place.
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/instance \
    && groupadd --gid "$APP_GID" appuser \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

# Everything Python runs from here: it is where run.py, migrations/ and the
# `app` package are, and gunicorn imports from the working directory.
WORKDIR /app/backend

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-120} run:app"]
