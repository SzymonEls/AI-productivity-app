# The client is built here and only its output is carried forward, so Node
# never reaches the image that runs in production.
FROM node:26-slim AS client

WORKDIR /client

COPY client/package.json client/package-lock.json ./
RUN npm ci

COPY client/ ./
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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# vite.config.ts writes here; the directory is git-ignored, so it arrives only
# from the stage above.
COPY --from=client /app/static/client ./app/static/client

# The repository root is /app, so its app/instance directory is /app/app/instance.
# That is where config.py looks for .env and the database - keep the volume,
# the entrypoint and DATABASE_URL pointed at the same place.
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/app/instance \
    && groupadd --gid "$APP_GID" appuser \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-120} run:app"]
