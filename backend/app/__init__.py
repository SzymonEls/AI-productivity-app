import os

from flask import Flask, jsonify, request
from flask_migrate import upgrade as apply_migrations
from sqlalchemy import inspect

from .config import Config

from .extensions import db, login_manager, migrate
from .api.revisions import register_tombstone_filter, register_write_stamping


def create_app(config_class=Config):
    """Application factory used by Flask commands and local development."""

    app = Flask(
        __name__,
        instance_path=getattr(config_class, "INSTANCE_PATH", None),
        instance_relative_config=True,
    )
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    register_tombstone_filter(db)
    register_write_stamping(db)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    from .models import LoginAttempt, Project, ProjectDaySlot, ProjectTimeEntry, ProjectTimelineGroup, ProjectTimelineItem, SyncState, User  # noqa: F401
    from .api.routes import api_bp
    from .api.pruning import register_pruning_command
    from .demo import register_demo_mode
    from .shell import main_bp

    app.register_blueprint(api_bp)
    # Last, because it answers every address the others did not claim.
    app.register_blueprint(main_bp)
    register_json_error_handlers(app)
    register_login_handlers(login_manager)
    # No-op unless DEMO_MODE is set: it registers nothing on the request path.
    register_demo_mode(app)
    register_pruning_command(app)
    if should_initialize_database(app):
        run_database_migrations(app)

    return app




def register_json_error_handlers(app):
    """Return JSON errors for fetch requests instead of HTML error pages."""

    @app.errorhandler(404)
    def not_found_error(error):
        if wants_json_response():
            return jsonify({"ok": False, "message": "This resource was not found."}), 404
        return error

    @app.errorhandler(500)
    def internal_error(error):
        if wants_json_response():
            return jsonify({"ok": False, "message": "A server error occurred while saving."}), 500
        return error

    @app.errorhandler(429)
    def too_many_requests(error):
        from flask import g

        return (
            jsonify(
                {
                    "ok": False,
                    "reason": "locked",
                    "message": (
                        "Too many failed sign-in attempts. Try again in "
                        f"{describe_wait(getattr(g, 'login_lock_seconds', 0))}."
                    ),
                }
            ),
            429,
        )


def register_login_handlers(manager):
    @manager.unauthorized_handler
    def unauthorized():
        """Always 401, never a redirect.

        There is no sign-in page to send anyone to any more: the client asks
        /api/me on start-up and draws its own form when the answer is this.
        """
        return jsonify({"ok": False, "message": "Session expired. Please sign in again."}), 401


def describe_wait(seconds):
    """Round the remaining lock up to whole minutes, which is all it promises."""
    if seconds <= 60:
        return "a minute"

    minutes = -(-seconds // 60)
    return f"{minutes} minutes"



def wants_json_response():
    return (
        request.headers.get("X-Requested-With") in {"XMLHttpRequest", "fetch"}
        or request.accept_mimetypes.best == "application/json"
    )


def should_initialize_database(app):
    """
    Keep local first-run bootstrap, but stay out of the way of Flask-Migrate.

    `flask db ...` commands should operate on the raw schema state instead of
    triggering automatic table creation before Alembic can inspect the models.
    """
    if app.config.get("SKIP_DB_BOOTSTRAP"):
        return False
    if os.environ.get("SKIP_DB_BOOTSTRAP") == "1":
        return False

    return True



def run_database_migrations(app):
    """
    Apply pending Alembic migrations automatically so local development
    (`flask --app run.py run`) doesn't need a manual `flask db upgrade` step.

    Docker already runs `flask db upgrade` once in docker-entrypoint.sh before
    starting Gunicorn, so this is skipped there via SKIP_DB_BOOTSTRAP to avoid
    every worker process racing to apply migrations at the same time.
    """
    from alembic.migration import MigrationContext

    with app.app_context():
        table_names = inspect(db.engine).get_table_names()

        with db.engine.connect() as connection:
            current_revision = MigrationContext.configure(connection).get_current_revision()

        if current_revision is None and table_names:
            # Tables, but no alembic_version: a database from before migrations
            # were adopted. This used to stamp it at head and carry on, which is
            # a guess - stamp() always writes head, without looking at the
            # schema. Right for a database that really is current and has only
            # lost its bookkeeping row; silently wrong for an older one, which
            # then reports itself as up to date while columns are missing.
            # Nothing here can tell the two apart, so it stops and asks.
            message = (
                "This database has tables but no alembic_version: it predates "
                "migrations, and nothing here can tell which revision its schema "
                "really matches. Nothing was changed. Stamp it by hand "
                "(flask db stamp <rev>) and start again."
            )
            app.logger.error(message)
            raise RuntimeError(message)

        apply_migrations()
