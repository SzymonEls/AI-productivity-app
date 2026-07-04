from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import DailyPlan, Project, ProjectTimelineGroup, ProjectTimelineItem
from ..time_tracking.service import project_last_session_labels


ai_bp = Blueprint("ai", __name__, url_prefix="/ai")


@ai_bp.route("/daily-plan/manual", methods=["GET", "POST"])
@login_required
def manual_daily_plan():
    projects = (
        Project.query.filter_by(user_id=current_user.id)
        .order_by(Project.is_starred.desc(), Project.title.asc())
        .all()
    )
    timeline_groups = _get_or_create_timeline(projects)

    if request.method == "GET":
        return render_template(
            "ai/manual_daily_plan.html",
            today=date.today(),
            projects=projects,
            timeline_groups=timeline_groups,
            project_last_session_labels=project_last_session_labels(current_user.id, projects),
        )

    raw_date = request.form.get("target_date", "").strip()
    try:
        target_date = date.fromisoformat(raw_date)
    except ValueError:
        flash("Choose a valid date for the daily plan.", "danger")
        return _render_manual_plan_template(date.today(), projects, timeline_groups), 400

    selected_project_ids = _parse_project_ids(request.form.getlist("project_ids"))
    if not selected_project_ids:
        flash("Choose at least one project for the manual plan.", "danger")
        return _render_manual_plan_template(target_date, projects, timeline_groups), 400

    selected_projects = (
        Project.query.filter(Project.user_id == current_user.id, Project.id.in_(selected_project_ids))
        .all()
    )
    project_by_id = {project.id: project for project in selected_projects}
    ordered_projects = [project_by_id[project_id] for project_id in selected_project_ids if project_id in project_by_id]

    if len(ordered_projects) != len(selected_project_ids):
        flash("Could not find all the selected projects.", "danger")
        return _render_manual_plan_template(target_date, projects, timeline_groups), 400

    for project in ordered_projects:
        short_goal = request.form.get(f"short_goal_{project.id}", "").strip()
        frequency = request.form.get(f"frequency_{project.id}", "").strip()
        long_goal = request.form.get(f"long_goal_{project.id}", "").strip()
        if short_goal:
            project.short_goal = short_goal
        if frequency:
            project.frequency = frequency
        if long_goal:
            project.long_goal = long_goal

    tasks = []
    for project in ordered_projects:
        project_tasks = _split_manual_project_tasks(request.form.get(f"task_{project.id}", ""))
        if not project_tasks:
            continue
        tasks.append({"project": project, "tasks": project_tasks})

    title = f"Daily plan - {target_date.isoformat()}"
    content = _render_manual_daily_plan(target_date, tasks)

    plan = DailyPlan.query.filter_by(user_id=current_user.id).first()
    if plan is None:
        plan = DailyPlan(owner=current_user)
        db.session.add(plan)
    plan.title = title
    plan.target_date = target_date
    plan.content = content

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to save the manual daily plan.", "danger")
        return _render_manual_plan_template(target_date, projects, timeline_groups), 500

    flash("The daily plan was saved.", "success")
    return redirect(url_for("main.home"))


def _render_manual_plan_template(target_date, projects, timeline_groups):
    return render_template(
        "ai/manual_daily_plan.html",
        today=target_date,
        projects=projects,
        timeline_groups=timeline_groups,
        project_last_session_labels=project_last_session_labels(current_user.id, projects),
    )


def _get_or_create_timeline(projects):
    groups = (
        ProjectTimelineGroup.query.filter_by(user_id=current_user.id)
        .order_by(ProjectTimelineGroup.position.asc(), ProjectTimelineGroup.id.asc())
        .all()
    )
    changed = False

    if not groups:
        groups = [ProjectTimelineGroup(owner=current_user, name="Projects", position=0)]
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


def _parse_project_ids(raw_project_ids):
    project_ids = []
    for raw_project_id in raw_project_ids:
        try:
            project_id = int(raw_project_id)
        except (TypeError, ValueError):
            continue
        if project_id not in project_ids:
            project_ids.append(project_id)
    return project_ids


def _split_manual_project_tasks(raw_tasks):
    return [line.strip() for line in raw_tasks.splitlines() if line.strip()]


def _render_manual_daily_plan(target_date, tasks):
    lines = [f"# Daily plan - {target_date.isoformat()}", ""]
    for item in tasks:
        project = item["project"]
        for task in item["tasks"]:
            lines.append(f"- **{project.title}:** {task}")
    return "\n".join(lines).strip() + "\n"
