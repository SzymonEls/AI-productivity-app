from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from ..ai.service import is_openai_configured
from ..extensions import db
from ..markdown_utils import render_markdown
from ..models import Project, ProjectTimelineGroup, ProjectTimelineItem


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
    timeline_groups = _get_or_create_timeline(projects)
    timeline_data = [_serialize_timeline_group(group) for group in timeline_groups]
    return render_template(
        "projects/dashboard.html",
        projects=projects,
        timeline_groups=timeline_groups,
        timeline_data=timeline_data,
    )


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


@projects_bp.route("/timeline", methods=["POST"])
@login_required
def save_timeline():
    payload = request.get_json(silent=True) or {}
    incoming_groups = payload.get("groups")
    if not isinstance(incoming_groups, list):
        return jsonify({"ok": False, "message": "Nieprawidlowy uklad timeline."}), 400

    projects = Project.query.filter_by(user_id=current_user.id).all()
    user_projects = {project.id: project for project in projects}
    existing_groups = {
        group.id: group
        for group in ProjectTimelineGroup.query.filter_by(user_id=current_user.id).all()
    }
    existing_items = {
        item.id: item
        for item in ProjectTimelineItem.query.filter_by(user_id=current_user.id).all()
    }

    saved_group_ids = set()
    saved_item_ids = set()
    seen_project_ids = set()

    try:
        for group_position, group_payload in enumerate(incoming_groups):
            if not isinstance(group_payload, dict):
                continue

            group_id = _coerce_int(group_payload.get("id"))
            group = existing_groups.get(group_id)
            if group is None:
                group = ProjectTimelineGroup(owner=current_user)
                db.session.add(group)

            group.name = (group_payload.get("name") or "").strip()[:150] or None
            group.position = group_position
            db.session.flush()
            saved_group_ids.add(group.id)

            incoming_items = group_payload.get("items") or []
            if not isinstance(incoming_items, list):
                incoming_items = []

            for item_position, item_payload in enumerate(incoming_items):
                if not isinstance(item_payload, dict):
                    continue

                item_type = item_payload.get("type")
                item_id = _coerce_int(item_payload.get("id"))
                item = existing_items.get(item_id)

                if item_type == "project":
                    project_id = _coerce_int(item_payload.get("project_id"))
                    if project_id not in user_projects or project_id in seen_project_ids:
                        continue
                    seen_project_ids.add(project_id)

                    if item is None or item.item_type != "project":
                        item = ProjectTimelineItem(owner=current_user)
                        db.session.add(item)
                    item.item_type = "project"
                    item.project_id = project_id
                    item.title = None
                    item.body = None
                elif item_type == "note":
                    title = (item_payload.get("title") or "").strip()[:180]
                    body = (item_payload.get("body") or "").strip()
                    if not title and not body:
                        continue

                    if item is None or item.item_type != "note":
                        item = ProjectTimelineItem(owner=current_user)
                        db.session.add(item)
                    item.item_type = "note"
                    item.project_id = None
                    item.title = title or "Notatka"
                    item.body = body
                else:
                    continue

                item.group = group
                item.position = item_position
                db.session.flush()
                saved_item_ids.add(item.id)

        for item_id, item in existing_items.items():
            if item_id not in saved_item_ids:
                db.session.delete(item)

        for group_id, group in existing_groups.items():
            if group_id not in saved_group_ids:
                db.session.delete(group)

        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Nie udalo sie zapisac timeline."}), 500

    timeline_groups = _get_or_create_timeline(projects)
    return jsonify({"ok": True, "groups": [_serialize_timeline_group(group) for group in timeline_groups]})


def _wants_json_response():
    return (
        request.headers.get("X-Requested-With") in {"XMLHttpRequest", "fetch"}
        or request.accept_mimetypes.best == "application/json"
    )


def _get_or_create_timeline(projects):
    groups = (
        ProjectTimelineGroup.query.filter_by(user_id=current_user.id)
        .order_by(ProjectTimelineGroup.position.asc(), ProjectTimelineGroup.id.asc())
        .all()
    )
    changed = False

    if not groups:
        groups = [ProjectTimelineGroup(owner=current_user, name="Projekty", position=0)]
        db.session.add(groups[0])
        db.session.flush()
        changed = True

    project_ids_on_timeline = {
        item.project_id
        for item in ProjectTimelineItem.query.filter_by(user_id=current_user.id, item_type="project").all()
        if item.project_id
    }
    default_group = groups[-1]
    next_position = len(default_group.items)

    for project in projects:
        if project.id in project_ids_on_timeline:
            continue
        db.session.add(
            ProjectTimelineItem(
                owner=current_user,
                group=default_group,
                project=project,
                item_type="project",
                position=next_position,
            )
        )
        next_position += 1
        changed = True

    if changed:
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()

    return (
        ProjectTimelineGroup.query.filter_by(user_id=current_user.id)
        .order_by(ProjectTimelineGroup.position.asc(), ProjectTimelineGroup.id.asc())
        .all()
    )


def _serialize_timeline_group(group):
    return {
        "id": group.id,
        "name": group.name or "",
        "items": [_serialize_timeline_item(item) for item in group.items],
    }


def _serialize_timeline_item(item):
    if item.item_type == "project":
        return {
            "id": item.id,
            "type": "project",
            "project_id": item.project_id,
            "title": item.project.title if item.project else "Projekt",
            "url": url_for("projects.project_detail", project_id=item.project_id) if item.project_id else "#",
        }

    return {
        "id": item.id,
        "type": "note",
        "title": item.title or "Notatka",
        "body": item.body or "",
    }


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
