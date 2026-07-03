import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, url_for
from flask_login import current_user
from sqlalchemy import inspect, text

from config import Config

from .extensions import db, login_manager, migrate
from .markdown_utils import render_markdown, render_project_markdown, strip_repeated_title


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
    login_manager.init_app(app)
    migrate.init_app(app, db)

    from .models import AIPlan, CalendarSubscription, Project, ProjectTimeEntry, ProjectTimelineGroup, ProjectTimelineItem, User  # noqa: F401
    from .ai.routes import ai_bp
    from .auth.routes import auth_bp
    from .calendar.routes import calendar_bp
    from .main.routes import main_bp
    from .projects.routes import projects_bp
    from .time_tracking.routes import time_tracking_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(time_tracking_bp)
    register_template_context(app)
    register_template_filters(app)
    register_json_error_handlers(app)
    register_login_handlers(login_manager)
    if should_initialize_database(app):
        initialize_database(app)

    return app


def register_template_context(app):
    """Expose shared feature flags to templates."""

    @app.context_processor
    def inject_feature_flags():
        active_time_entry = None
        active_time_elapsed_seconds = 0
        active_time_elapsed_label = ""
        if current_user.is_authenticated:
            from .time_tracking.service import active_entry_for_user, today_project_summary

            active_time_entry = active_entry_for_user(current_user.id)
            if active_time_entry:
                active_time_elapsed_seconds = today_project_summary(
                    current_user.id,
                    active_time_entry.project_id,
                )["total_seconds"]
                elapsed_minutes = active_time_elapsed_seconds // 60
                elapsed_hours = elapsed_minutes // 60
                remaining_minutes = elapsed_minutes % 60
                if elapsed_hours:
                    active_time_elapsed_label = f"{elapsed_hours}h {remaining_minutes:02d}m"
                else:
                    active_time_elapsed_label = f"{elapsed_minutes}m"

        return {
            "app_version": app.config.get("APP_VERSION", "local"),
            "registration_enabled": app.config.get("REGISTRATION_ENABLED", True),
            "ai_enabled": app.config.get("AI_ENABLED", True),
            "calendar_enabled": app.config.get("CALENDAR_ENABLED", True),
            "active_time_entry": active_time_entry,
            "active_time_elapsed_seconds": active_time_elapsed_seconds,
            "active_time_elapsed_label": active_time_elapsed_label,
        }


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


def register_login_handlers(manager):
    @manager.unauthorized_handler
    def unauthorized():
        if wants_json_response():
            return jsonify({"ok": False, "message": "Session expired. Please log in again."}), 401
        return redirect_to_login()


def redirect_to_login():
    from flask import redirect

    login_url = url_for(login_manager.login_view, next=request.url)
    return redirect(login_url)


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


def register_template_filters(app):
    """Register shared Jinja filters used across the UI."""

    @app.template_filter("markdown")
    def markdown_filter(value):
        return render_markdown(value)

    @app.template_filter("project_markdown")
    def project_markdown_filter(value):
        return render_project_markdown(value)

    @app.template_filter("without_repeated_title")
    def without_repeated_title_filter(value, title):
        return strip_repeated_title(value, title)

    @app.template_filter("naturaltime")
    def naturaltime_filter(value):
        if not value:
            return ""

        current_time = datetime.now(timezone.utc)
        timestamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        seconds = int(max((current_time - timestamp).total_seconds(), 0))

        if seconds < 10:
            return "just now"
        if seconds < 60:
            return f"{seconds} seconds ago"

        minutes = seconds // 60
        if minutes == 1:
            return "1 minute ago"
        if minutes < 60:
            return f"{minutes} minutes ago"

        hours = minutes // 60
        if hours == 1:
            return "1 hour ago"
        if hours < 24:
            return f"{hours} hours ago"

        days = hours // 24
        if days == 1:
            return "1 day ago"
        if days < 30:
            return f"{days} days ago"

        months = days // 30
        if months == 1:
            return "1 month ago"
        if months < 12:
            return f"{months} months ago"

        years = days // 365
        return "1 year ago" if years == 1 else f"{years} years ago"


def initialize_database(app):
    """
    Create tables automatically when the configured database is empty.

    This keeps first-run local setup simple while still allowing the project
    to adopt migrations as it grows.
    """
    from .models import AIPlan, CalendarSubscription, ProjectTimeEntry, ProjectTimelineGroup, ProjectTimelineItem

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

        if "calendar_subscriptions" not in table_names:
            CalendarSubscription.__table__.create(bind=db.engine)

        if "ai_plans" not in table_names:
            AIPlan.__table__.create(bind=db.engine)
        else:
            ai_plan_columns = {column["name"] for column in inspector.get_columns("ai_plans")}
            if "request_payload" not in ai_plan_columns:
                db.session.execute(text("ALTER TABLE ai_plans ADD COLUMN request_payload TEXT"))
                db.session.commit()
            if "is_pinned" not in ai_plan_columns:
                db.session.execute(
                    text(
                        "ALTER TABLE ai_plans ADD COLUMN is_pinned BOOLEAN "
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
        if "project_timeline_groups" not in table_names:
            ProjectTimelineGroup.__table__.create(bind=db.engine)

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
