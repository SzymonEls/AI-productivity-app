import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_login import current_user
from flask_migrate import stamp as stamp_migrations, upgrade as apply_migrations
from sqlalchemy import inspect, text

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
        initialize_database(app)

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
            # Existing local database predates Alembic tracking. Its schema is
            # kept compatible by the ad-hoc bootstrap below, so mark it as
            # being at the latest migration instead of replaying every
            # migration's upgrade() against tables that already exist.
            stamp_migrations()
            return

        apply_migrations()


def initialize_database(app):
    """
    Create tables automatically when the configured database is empty.

    This keeps first-run local setup simple while still allowing the project
    to adopt migrations as it grows.
    """
    from .models import ProjectTimeEntry, ProjectTimelineGroup, ProjectTimelineItem

    with app.app_context():
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        if not table_names:
            # Only create tables for a brand-new database.
            # Once tables exist, we leave schema changes to migrations.
            db.create_all()
            return

        if "projects" in table_names:
            project_columns = {column["name"] for column in inspector.get_columns("projects")}
            if "updated_at" not in project_columns:
                # Lightweight compatibility step for older local SQLite files.
                db.session.execute(text("ALTER TABLE projects ADD COLUMN updated_at DATETIME"))
                db.session.execute(
                    text("UPDATE projects SET updated_at = created_at WHERE updated_at IS NULL")
                )
                db.session.commit()
            if "frequency" not in project_columns:
                # Keep existing local databases usable when new project fields are added.
                db.session.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN frequency VARCHAR(255) "
                        "DEFAULT 'Once a week' NOT NULL"
                    )
                )
                db.session.commit()
            if "is_starred" not in project_columns:
                db.session.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN is_starred BOOLEAN "
                        "DEFAULT 0 NOT NULL"
                    )
                )
                db.session.commit()
            if "archived_long_goal" not in project_columns:
                db.session.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN archived_long_goal TEXT "
                        "DEFAULT '' NOT NULL"
                    )
                )
                db.session.commit()
            if "is_archived" not in project_columns:
                db.session.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN is_archived BOOLEAN "
                        "DEFAULT 0 NOT NULL"
                    )
                )
                db.session.commit()
            if "is_private" not in project_columns:
                db.session.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN is_private BOOLEAN "
                        "DEFAULT 0 NOT NULL"
                    )
                )
                db.session.commit()

        if "users" in table_names:
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            if "session_token" not in user_columns:
                # Pre-Alembic local databases are stamped at head rather than
                # migrated, so the column has to be added here as well.
                import secrets

                db.session.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN session_token VARCHAR(64) "
                        "DEFAULT '' NOT NULL"
                    )
                )
                for row in db.session.execute(text("SELECT id FROM users")).fetchall():
                    db.session.execute(
                        text("UPDATE users SET session_token = :token WHERE id = :id"),
                        {"token": secrets.token_hex(32), "id": row.id},
                    )
                db.session.commit()

        if "project_timeline_groups" not in table_names:
            ProjectTimelineGroup.__table__.create(bind=db.engine)
        else:
            timeline_group_columns = {column["name"] for column in inspector.get_columns("project_timeline_groups")}
            if "is_backlog" not in timeline_group_columns:
                db.session.execute(
                    text(
                        "ALTER TABLE project_timeline_groups ADD COLUMN is_backlog BOOLEAN "
                        "DEFAULT 0 NOT NULL"
                    )
                )
                db.session.commit()

        if "project_timeline_items" not in table_names:
            ProjectTimelineItem.__table__.create(bind=db.engine)
        else:
            timeline_item_columns = {column["name"] for column in inspector.get_columns("project_timeline_items")}
            if "is_private" not in timeline_item_columns:
                db.session.execute(
                    text(
                        "ALTER TABLE project_timeline_items ADD COLUMN is_private BOOLEAN "
                        "DEFAULT 0 NOT NULL"
                    )
                )
                db.session.commit()

        if "project_time_entries" not in table_names:
            ProjectTimeEntry.__table__.create(bind=db.engine)
        else:
            time_entry_columns = inspector.get_columns("project_time_entries")
            time_entry_column_names = {column["name"] for column in time_entry_columns}
            if "project_title_snapshot" not in time_entry_column_names:
                db.session.execute(
                    text("ALTER TABLE project_time_entries ADD COLUMN project_title_snapshot VARCHAR(150)")
                )
                db.session.execute(
                    text(
                        "UPDATE project_time_entries SET project_title_snapshot = ("
                        "SELECT title FROM projects WHERE projects.id = project_time_entries.project_id"
                        ") WHERE project_title_snapshot IS NULL AND project_id IS NOT NULL"
                    )
                )
                db.session.commit()

            project_id_column = next(
                column for column in time_entry_columns if column["name"] == "project_id"
            )
            if not project_id_column["nullable"]:
                _allow_null_time_entry_project_id(db)


def _allow_null_time_entry_project_id(db):
    """
    Relax project_time_entries.project_id to nullable so deleting a project
    orphans its time entries instead of failing/cascading. SQLite has no
    ALTER COLUMN, so the table is rebuilt; other dialects can alter in place.
    """
    if db.engine.dialect.name == "sqlite":
        db.session.execute(text("ALTER TABLE project_time_entries RENAME TO project_time_entries_old"))
        db.session.execute(
            text(
                """
                CREATE TABLE project_time_entries (
                    id INTEGER NOT NULL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    project_id INTEGER,
                    started_at DATETIME NOT NULL,
                    ended_at DATETIME,
                    description TEXT,
                    project_title_snapshot VARCHAR(150),
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects (id),
                    FOREIGN KEY(user_id) REFERENCES users (id)
                )
                """
            )
        )
        db.session.execute(
            text(
                "INSERT INTO project_time_entries "
                "(id, user_id, project_id, started_at, ended_at, description, "
                "project_title_snapshot, created_at, updated_at) "
                "SELECT id, user_id, project_id, started_at, ended_at, description, "
                "project_title_snapshot, created_at, updated_at "
                "FROM project_time_entries_old"
            )
        )
        db.session.execute(text("DROP TABLE project_time_entries_old"))
        db.session.execute(
            text(
                "CREATE INDEX ix_project_time_entries_user_project_started "
                "ON project_time_entries (user_id, project_id, started_at)"
            )
        )
        db.session.execute(
            text("CREATE INDEX ix_project_time_entries_user_ended ON project_time_entries (user_id, ended_at)")
        )
    else:
        db.session.execute(text("ALTER TABLE project_time_entries ALTER COLUMN project_id DROP NOT NULL"))
    db.session.commit()
