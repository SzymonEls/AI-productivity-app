import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, url_for
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

    from .models import AIPlan, CalendarSubscription, Project, ProjectTimelineGroup, ProjectTimelineItem, User  # noqa: F401
    from .ai.routes import ai_bp
    from .auth.routes import auth_bp
    from .calendar.routes import calendar_bp
    from .main.routes import main_bp
    from .projects.routes import projects_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(projects_bp)
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
        return {
            "registration_enabled": app.config.get("REGISTRATION_ENABLED", True),
        }


def register_json_error_handlers(app):
    """Return JSON errors for fetch requests instead of HTML error pages."""

    @app.errorhandler(404)
    def not_found_error(error):
        if wants_json_response():
            return jsonify({"ok": False, "message": "Nie znaleziono tego zasobu."}), 404
        return error

    @app.errorhandler(500)
    def internal_error(error):
        if wants_json_response():
            return jsonify({"ok": False, "message": "Wystapil blad serwera podczas zapisu."}), 500
        return error


def register_login_handlers(manager):
    @manager.unauthorized_handler
    def unauthorized():
        if wants_json_response():
            return jsonify({"ok": False, "message": "Sesja wygasla. Zaloguj sie ponownie."}), 401
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
    from .models import AIPlan, CalendarSubscription, ProjectTimelineGroup, ProjectTimelineItem

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
