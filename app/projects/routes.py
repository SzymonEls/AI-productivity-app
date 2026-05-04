from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from ..ai.service import is_openai_configured
from ..extensions import db
from ..markdown_utils import render_markdown
from ..models import Project


projects_bp = Blueprint("projects", __name__, url_prefix="/projects")


def _get_user_project_or_404(project_id):
    """Ensure users can only access their own projects."""

    return Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()


@projects_bp.route("/dashboard")
@login_required
def dashboard():
    projects = (
        Project.query.filter_by(user_id=current_user.id)
        .order_by(Project.is_starred.desc(), func.lower(Project.title).asc())
        .all()
    )
    return render_template("projects/dashboard.html", projects=projects)


@projects_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_project():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        short_goal = request.form.get("short_goal", "").strip()
        frequency = request.form.get("frequency", "").strip()
        long_goal = request.form.get("long_goal", "").strip()

        if not title or not short_goal or not frequency or not long_goal:
            flash("Please complete all project fields.", "danger")
        else:
            project = Project(
                title=title,
                short_goal=short_goal,
                frequency=frequency,
                long_goal=long_goal,
                owner=current_user,
            )
            db.session.add(project)
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                flash("Nie udalo sie utworzyc projektu. Baza danych jest niedostepna do zapisu.", "danger")
                return render_template(
                    "projects/project_form.html",
                    page_title="Create Project",
                    form_title="New Project",
                    submit_label="Create Project",
                    project=None,
                )
            flash("Project created successfully.", "success")
            return redirect(url_for("projects.dashboard"))

    return render_template(
        "projects/project_form.html",
        page_title="Create Project",
        form_title="New Project",
        submit_label="Create Project",
        project=None,
    )


@projects_bp.route("/<int:project_id>")
@login_required
def project_detail(project_id):
    project = _get_user_project_or_404(project_id)
    return render_template(
        "projects/project_detail.html",
        project=project,
        is_openai_ready=is_openai_configured(),
    )


@projects_bp.route("/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    project = _get_user_project_or_404(project_id)

    if request.method == "GET":
        return redirect(url_for("projects.project_detail", project_id=project.id))

    title = request.form.get("title", "").strip()
    short_goal = request.form.get("short_goal", "").strip()
    frequency = request.form.get("frequency", "").strip()
    long_goal = request.form.get("long_goal", "").strip()
    starred_value = request.form.get("is_starred")
    is_starred = project.is_starred if starred_value is None else starred_value.lower() in {"1", "true", "on", "yes"}

    if not title or not short_goal or not frequency or not long_goal:
        error_message = "Please complete all project fields."
        if _wants_json_response():
            return jsonify({"ok": False, "message": error_message}), 400
        flash(error_message, "danger")
    else:
        project.title = title
        project.short_goal = short_goal
        project.frequency = frequency
        project.long_goal = long_goal
        project.is_starred = is_starred
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            error_message = "Nie udalo sie zapisac projektu. Baza danych jest niedostepna do zapisu."
            if _wants_json_response():
                return jsonify({"ok": False, "message": error_message}), 500
            flash(error_message, "danger")
            return redirect(url_for("projects.project_detail", project_id=project.id))

        success_message = "Project updated successfully."
        if _wants_json_response():
            return jsonify(
                {
                    "ok": True,
                    "message": success_message,
                    "project": {
                        "title": project.title,
                        "short_goal": project.short_goal,
                        "frequency": project.frequency,
                        "long_goal": project.long_goal,
                        "long_goal_html": str(render_markdown(project.long_goal)),
                        "is_starred": project.is_starred,
                        "updated_label": "just now",
                    },
                }
            )
        flash(success_message, "success")

    return redirect(url_for("projects.project_detail", project_id=project.id))


@projects_bp.route("/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    project = _get_user_project_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    flash("Project deleted.", "info")
    return redirect(url_for("projects.dashboard"))


def _wants_json_response():
    return (
        request.headers.get("X-Requested-With") in {"XMLHttpRequest", "fetch"}
        or request.accept_mimetypes.best == "application/json"
    )
