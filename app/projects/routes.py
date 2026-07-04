from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..markdown_utils import render_project_markdown
from ..models import Project, ProjectTimelineGroup, ProjectTimelineItem
from ..time_tracking.service import project_last_session_labels, today_project_summary, utc_now


projects_bp = Blueprint("projects", __name__, url_prefix="/projects")


def _get_user_project_or_404(project_id):
    """Ensure users can only access their own projects."""

    return Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()


@projects_bp.route("/dashboard")
@login_required
def dashboard():
    projects = (
        Project.query.filter_by(user_id=current_user.id, is_archived=False)
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    timeline_groups, backlog_group = _get_or_create_timeline(projects)
    last_session_labels = project_last_session_labels(current_user.id, projects)
    timeline_data = [_serialize_timeline_group(group, last_session_labels) for group in timeline_groups]
    backlog_data = _serialize_timeline_group(backlog_group, last_session_labels)
    return render_template(
        "projects/dashboard.html",
        projects=projects,
        timeline_groups=timeline_groups,
        timeline_data=timeline_data,
        backlog_group=backlog_group,
        backlog_data=backlog_data,
        project_last_session_labels=last_session_labels,
    )


@projects_bp.route("/archived")
@login_required
def archived_projects():
    projects = (
        Project.query.filter_by(user_id=current_user.id, is_archived=True)
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    return render_template("projects/archived.html", projects=projects)


@projects_bp.route("/<int:project_id>/archive", methods=["POST"])
@login_required
def archive_project(project_id):
    project = _get_user_project_or_404(project_id)
    project.is_archived = True
    db.session.commit()
    flash("Project archived.", "info")
    return redirect(url_for("projects.dashboard"))


@projects_bp.route("/<int:project_id>/unarchive", methods=["POST"])
@login_required
def unarchive_project(project_id):
    project = _get_user_project_or_404(project_id)
    project.is_archived = False
    db.session.commit()
    flash("Project restored.", "info")
    if request.form.get("next") == "detail":
        return redirect(url_for("projects.project_detail", project_id=project.id))
    return redirect(url_for("projects.archived_projects"))


@projects_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_project():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        short_goal = request.form.get("short_goal", "").strip()
        frequency = request.form.get("frequency", "").strip()
        long_goal = request.form.get("long_goal", "").strip()
        is_private = _form_bool("is_private", default=False)

        if not title or not short_goal or not frequency or not long_goal:
            flash("Please complete all project fields.", "danger")
        else:
            project = Project(
                title=title,
                short_goal=short_goal,
                frequency=frequency,
                long_goal=long_goal,
                is_private=is_private,
                owner=current_user,
            )
            db.session.add(project)
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                flash("Failed to create the project. The database is unavailable for writing.", "danger")
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
        timer_summary=today_project_summary(current_user.id, project.id),
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
    is_private = _form_bool("is_private", default=project.is_private)

    if not title or not short_goal or not frequency:
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
        project.is_private = is_private
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            error_message = "Failed to save the project. The database is unavailable for writing."
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
                        "long_goal_html": str(render_project_markdown(project.long_goal)),
                        "archived_long_goal": project.archived_long_goal or "",
                        "archived_long_goal_html": str(render_project_markdown(project.archived_long_goal or "")),
                        "has_archived_long_goal": bool((project.archived_long_goal or "").strip()),
                        "is_starred": project.is_starred,
                        "is_private": project.is_private,
                        "updated_label": "just now",
                    },
                }
            )
        flash(success_message, "success")

    return redirect(url_for("projects.project_detail", project_id=project.id))


@projects_bp.route("/<int:project_id>/archive-section", methods=["POST"])
@login_required
def archive_project_section(project_id):
    project = _get_user_project_or_404(project_id)
    section_index = _coerce_int(request.form.get("section_index"))
    if section_index is None:
        return jsonify({"ok": False, "message": "No sections were selected to archive."}), 400

    try:
        active_plan, archived_section = _remove_top_level_markdown_section(project.long_goal, section_index)
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400

    project.long_goal = active_plan
    project.archived_long_goal = _append_markdown_section(project.archived_long_goal or "", archived_section)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to archive the section(s)."}), 500

    return jsonify(
        {
            "ok": True,
            "message": "The section was moved to the archive.",
            "project": {
                "title": project.title,
                "short_goal": project.short_goal,
                "frequency": project.frequency,
                "long_goal": project.long_goal,
                "long_goal_html": str(render_project_markdown(project.long_goal)),
                "archived_long_goal": project.archived_long_goal or "",
                "archived_long_goal_html": str(render_project_markdown(project.archived_long_goal or "")),
                "has_archived_long_goal": bool((project.archived_long_goal or "").strip()),
                "is_starred": project.is_starred,
                "is_private": project.is_private,
                "updated_label": "just now",
            },
        }
    )


@projects_bp.route("/<int:project_id>/restore-section", methods=["POST"])
@login_required
def restore_project_section(project_id):
    project = _get_user_project_or_404(project_id)
    section_index = _coerce_int(request.form.get("section_index"))
    if section_index is None:
        return jsonify({"ok": False, "message": "No sections were selected to restore."}), 400

    try:
        archived_plan, restored_section = _remove_top_level_markdown_section(
            project.archived_long_goal,
            section_index,
            empty_message="Archive has no section # to restore.",
        )
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400

    project.archived_long_goal = archived_plan
    project.long_goal = _append_markdown_section(project.long_goal or "", restored_section)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to restore the section(s)."}), 500

    return jsonify(
        {
            "ok": True,
            "message": "The section was restored from the archive.",
            "project": {
                "title": project.title,
                "short_goal": project.short_goal,
                "frequency": project.frequency,
                "long_goal": project.long_goal,
                "long_goal_html": str(render_project_markdown(project.long_goal)),
                "archived_long_goal": project.archived_long_goal or "",
                "archived_long_goal_html": str(render_project_markdown(project.archived_long_goal or "")),
                "has_archived_long_goal": bool((project.archived_long_goal or "").strip()),
                "is_starred": project.is_starred,
                "is_private": project.is_private,
                "updated_label": "just now",
            },
        }
    )


@projects_bp.route("/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    project = _get_user_project_or_404(project_id)
    for entry in project.time_entries:
        if entry.ended_at is None:
            entry.ended_at = utc_now()
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
        return jsonify({"ok": False, "message": "Invalid timeline layout."}), 400

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
                    item = _upsert_project_item(item, item_payload, user_projects, seen_project_ids)
                    if item is None:
                        continue
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
                    item.title = title or "Note"
                    item.body = body
                    item.is_private = bool(item_payload.get("is_private"))
                elif item_type == "project_from_note":
                    title = (item_payload.get("title") or "").strip()[:150]
                    body = (item_payload.get("body") or "").strip()
                    if not title and body:
                        title = body.splitlines()[0].strip()[:150]
                    title = title or "Project"
                    project = Project(
                        owner=current_user,
                        title=title,
                        short_goal=body or "-",
                        frequency="-",
                        long_goal=body or "-",
                        is_private=bool(item_payload.get("is_private")),
                    )
                    db.session.add(project)
                    db.session.flush()
                    seen_project_ids.add(project.id)

                    if item is None:
                        item = ProjectTimelineItem(owner=current_user)
                        db.session.add(item)
                    item.item_type = "project"
                    item.project = project
                    item.title = None
                    item.body = None
                    item.is_private = False
                else:
                    continue

                item.group = group
                item.position = item_position
                db.session.flush()
                saved_item_ids.add(item.id)

        backlog_group = _get_backlog_group()
        saved_group_ids.add(backlog_group.id)

        incoming_backlog = payload.get("backlog")
        if isinstance(incoming_backlog, list):
            for item_position, item_payload in enumerate(incoming_backlog):
                if not isinstance(item_payload, dict) or item_payload.get("type") != "project":
                    continue
                item = existing_items.get(_coerce_int(item_payload.get("id")))
                item = _upsert_project_item(item, item_payload, user_projects, seen_project_ids)
                if item is None:
                    continue
                item.group = backlog_group
                item.position = item_position
                db.session.flush()
                saved_item_ids.add(item.id)
        else:
            # No backlog payload sent: keep whatever is already parked off-timeline.
            for existing_id, existing_item in existing_items.items():
                if existing_item.group_id == backlog_group.id:
                    saved_item_ids.add(existing_id)

        for item_id, item in existing_items.items():
            if item_id not in saved_item_ids:
                db.session.delete(item)

        for group_id, group in existing_groups.items():
            if group_id not in saved_group_ids:
                db.session.delete(group)

        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the timeline."}), 500

    timeline_groups, backlog_group = _get_or_create_timeline(projects)
    last_session_labels = project_last_session_labels(current_user.id, projects)
    return jsonify(
        {
            "ok": True,
            "groups": [_serialize_timeline_group(group, last_session_labels) for group in timeline_groups],
            "backlog": _serialize_timeline_group(backlog_group, last_session_labels),
        }
    )


def _upsert_project_item(item, item_payload, user_projects, seen_project_ids):
    """Create or reuse a timeline item that references an existing project."""

    project_id = _coerce_int(item_payload.get("project_id"))
    if project_id not in user_projects or project_id in seen_project_ids:
        return None
    seen_project_ids.add(project_id)

    if item is None or item.item_type != "project":
        item = ProjectTimelineItem(owner=current_user)
        db.session.add(item)
    item.item_type = "project"
    item.project_id = project_id
    item.title = None
    item.body = None
    item.is_private = False
    return item


def _wants_json_response():
    return (
        request.headers.get("X-Requested-With") in {"XMLHttpRequest", "fetch"}
        or request.accept_mimetypes.best == "application/json"
    )


def _get_backlog_group():
    """Return (creating if needed) the off-timeline group that parks projects."""

    backlog_group = ProjectTimelineGroup.query.filter_by(
        user_id=current_user.id, is_backlog=True
    ).first()
    if backlog_group is None:
        backlog_group = ProjectTimelineGroup(owner=current_user, is_backlog=True, position=0)
        db.session.add(backlog_group)
        db.session.flush()
    return backlog_group


def _get_or_create_timeline(projects):
    groups = (
        ProjectTimelineGroup.query.filter_by(user_id=current_user.id, is_backlog=False)
        .order_by(ProjectTimelineGroup.position.asc(), ProjectTimelineGroup.id.asc())
        .all()
    )
    changed = False

    if not groups:
        groups = [ProjectTimelineGroup(owner=current_user, name="Projects", position=0)]
        db.session.add(groups[0])
        db.session.flush()
        changed = True

    backlog_group = _get_backlog_group()

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

    groups = (
        ProjectTimelineGroup.query.filter_by(user_id=current_user.id, is_backlog=False)
        .order_by(ProjectTimelineGroup.position.asc(), ProjectTimelineGroup.id.asc())
        .all()
    )
    return groups, _get_backlog_group()


def _serialize_timeline_group(group, last_session_labels=None):
    return {
        "id": group.id,
        "name": group.name or "",
        "items": [
            _serialize_timeline_item(item, last_session_labels)
            for item in group.items
            if item.item_type != "project" or (item.project and not item.project.is_archived)
        ],
    }


def _serialize_timeline_item(item, last_session_labels=None):
    if item.item_type == "project":
        last_session_labels = last_session_labels or {}
        return {
            "id": item.id,
            "type": "project",
            "project_id": item.project_id,
            "title": item.project.title if item.project else "Project",
            "url": url_for("projects.project_detail", project_id=item.project_id) if item.project_id else "#",
            "is_private": bool(item.project.is_private) if item.project else False,
            "frequency": item.project.frequency if item.project else "",
            "last_session_label": last_session_labels.get(item.project_id, "Last session: none"),
        }

    return {
        "id": item.id,
        "type": "note",
        "title": item.title or "Note",
        "body": item.body or "",
        "is_private": bool(item.is_private),
    }


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _remove_top_level_markdown_section(markdown, section_index, empty_message="This plan has no section # to archive."):
    sections = _top_level_markdown_section_ranges(markdown or "")
    if not sections:
        raise ValueError(empty_message)
    if section_index < 0 or section_index >= len(sections):
        raise ValueError("The selected section was not found.")

    start, end = sections[section_index]
    archived_section = (markdown or "")[start:end].strip()
    active_plan = f"{(markdown or '')[:start].rstrip()}\n\n{(markdown or '')[end:].lstrip()}".strip()
    return active_plan, archived_section


def _top_level_markdown_section_ranges(markdown):
    lines = (markdown or "").splitlines(keepends=True)
    heading_offsets = []
    offset = 0
    for line in lines:
        if line.startswith("# ") and line.strip()[2:].strip():
            heading_offsets.append(offset)
        offset += len(line)

    ranges = []
    for index, start in enumerate(heading_offsets):
        end = heading_offsets[index + 1] if index + 1 < len(heading_offsets) else len(markdown or "")
        ranges.append((start, end))
    return ranges


def _append_markdown_section(markdown, section):
    current = (markdown or "").strip()
    section = (section or "").strip()
    if not current:
        return section
    return f"{current}\n\n{section}"


def _form_bool(name, default=False):
    value = request.form.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "on", "yes"}
