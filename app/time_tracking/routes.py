from collections import defaultdict
from datetime import timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Project, ProjectTimeEntry
from .service import (
    active_entry_for_user,
    app_timezone,
    daily_totals_by_project,
    day_bounds_utc,
    entries_for_range,
    ensure_utc,
    entry_elapsed_seconds,
    entry_overlap_seconds,
    format_duration,
    local_datetime_value,
    parse_local_date,
    parse_local_datetime,
    today_project_summary,
    utc_now,
)


time_tracking_bp = Blueprint("time_tracking", __name__, url_prefix="/time-tracking")


def _get_user_project_or_404(project_id):
    return Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()


def _entry_payload(entry):
    return {
        "id": entry.id,
        "project_id": entry.project_id,
        "project_title": entry.project.title,
        "started_at": local_datetime_value(entry.started_at),
        "ended_at": local_datetime_value(entry.ended_at),
        "description": entry.description or "",
        "duration_seconds": entry_elapsed_seconds(entry),
        "duration_label": format_duration(entry_elapsed_seconds(entry)),
        "is_running": entry.ended_at is None,
    }


@time_tracking_bp.route("/")
@login_required
def index():
    today = utc_now().astimezone(app_timezone()).date()
    date_mode = request.args.get("date_mode") or "day"
    all_dates = date_mode == "all"
    selected_day = None if all_dates else parse_local_date(request.args.get("date"), default=today)
    selected_project_id = request.args.get("project_id", type=int)
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    projects = (
        Project.query.filter_by(user_id=current_user.id)
        .order_by(Project.is_starred.desc(), Project.title.asc())
        .all()
    )
    selected_project = next((project for project in projects if project.id == selected_project_id), None)

    entries_query = ProjectTimeEntry.query.filter_by(user_id=current_user.id)
    if selected_project:
        entries_query = entries_query.filter_by(project_id=selected_project.id)
    if selected_day:
        day_start, day_end = day_bounds_utc(selected_day)
        entries_query = entries_query.filter(ProjectTimeEntry.started_at <= day_end).filter(
            (ProjectTimeEntry.ended_at.is_(None)) | (ProjectTimeEntry.ended_at >= day_start)
        )

    entries_pagination = entries_query.order_by(ProjectTimeEntry.started_at.desc()).paginate(
        page=page,
        per_page=50,
        error_out=False,
    )
    visible_entries = entries_pagination.items

    chart_projects = []
    if selected_day and not selected_project:
        totals_by_project = daily_totals_by_project(current_user.id, selected_day)
        chart_projects = [
            {
                "id": project.id,
                "title": project.title,
                "seconds": totals_by_project.get(project.id, 0),
                "label": format_duration(totals_by_project.get(project.id, 0)),
            }
            for project in projects
            if totals_by_project.get(project.id, 0) > 0
        ]
    day_total_seconds = sum(item["seconds"] for item in chart_projects)
    selected_project_day_seconds = 0
    if selected_day and selected_project:
        day_start, day_end = day_bounds_utc(selected_day)
        selected_project_day_seconds = sum(
            entry_overlap_seconds(entry, day_start, day_end)
            for entry in entries_for_range(current_user.id, day_start, day_end, project_id=selected_project.id)
        )

    project_daily_chart = []
    if all_dates and selected_project:
        for offset in range(13, -1, -1):
            day = today - timedelta(days=offset)
            range_start, range_end = day_bounds_utc(day)
            entries = entries_for_range(current_user.id, range_start, range_end, project_id=selected_project.id)
            seconds = sum(entry_overlap_seconds(entry, range_start, range_end) for entry in entries)
            project_daily_chart.append(
                {
                    "date": day.isoformat(),
                    "label": day.strftime("%d.%m"),
                    "seconds": seconds,
                    "duration": format_duration(seconds),
                }
            )

    active_entry = active_entry_for_user(current_user.id)
    return render_template(
        "time_tracking/index.html",
        projects=projects,
        date_mode="all" if all_dates else "day",
        all_dates=all_dates,
        today=today,
        selected_day=selected_day,
        selected_project=selected_project,
        selected_project_id=selected_project.id if selected_project else "",
        entries=visible_entries,
        entries_pagination=entries_pagination,
        chart_projects=chart_projects,
        day_total_seconds=day_total_seconds,
        selected_project_day_seconds=selected_project_day_seconds,
        project_daily_chart=project_daily_chart,
        entry_elapsed_seconds=entry_elapsed_seconds,
        format_duration=format_duration,
        local_datetime_value=local_datetime_value,
        active_entry=active_entry,
    )


@time_tracking_bp.route("/projects/<int:project_id>/status")
@login_required
def project_status(project_id):
    project = _get_user_project_or_404(project_id)
    summary = today_project_summary(current_user.id, project.id)
    return jsonify(_project_timer_payload(project, summary))


@time_tracking_bp.route("/projects/<int:project_id>/start", methods=["POST"])
@login_required
def start_project_timer(project_id):
    project = _get_user_project_or_404(project_id)
    active_entry = active_entry_for_user(current_user.id)
    if active_entry and active_entry.project_id != project.id:
        return jsonify(
            {
                "ok": False,
                "message": f"Zatrzymaj najpierw timer projektu: {active_entry.project.title}.",
                "active_project_url": url_for("projects.project_detail", project_id=active_entry.project_id),
            }
        ), 409

    if not active_entry:
        db.session.add(ProjectTimeEntry(owner=current_user, project=project, started_at=utc_now()))

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Nie udalo sie uruchomic timera."}), 500

    return jsonify(_project_timer_payload(project, today_project_summary(current_user.id, project.id)))


@time_tracking_bp.route("/projects/<int:project_id>/pause", methods=["POST"])
@login_required
def pause_project_timer(project_id):
    project = _get_user_project_or_404(project_id)
    description = (request.form.get("description") or "").strip()
    active_entry = (
        ProjectTimeEntry.query.filter_by(user_id=current_user.id, project_id=project.id, ended_at=None)
        .order_by(ProjectTimeEntry.started_at.desc())
        .first()
    )
    if active_entry:
        active_entry.description = description or None
        active_entry.ended_at = utc_now()

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Nie udalo sie zatrzymac timera."}), 500

    return jsonify(_project_timer_payload(project, today_project_summary(current_user.id, project.id)))


@time_tracking_bp.route("/projects/<int:project_id>/description", methods=["POST"])
@login_required
def save_today_description(project_id):
    project = _get_user_project_or_404(project_id)
    description = (request.form.get("description") or "").strip()
    summary = today_project_summary(current_user.id, project.id)
    entry = summary["active_entry"]
    if entry is None:
        return jsonify({"ok": False, "message": "Rozpocznij nowa sesje, zeby zapisac jej opis."}), 409
    entry.description = description or None

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Nie udalo sie zapisac opisu."}), 500

    return jsonify(_project_timer_payload(project, today_project_summary(current_user.id, project.id)))


@time_tracking_bp.route("/entries/<int:entry_id>/edit", methods=["POST"])
@login_required
def edit_entry(entry_id):
    entry = ProjectTimeEntry.query.filter_by(id=entry_id, user_id=current_user.id).first_or_404()
    project_id = request.form.get("project_id", type=int) or entry.project_id
    project = _get_user_project_or_404(project_id)
    started_at = parse_local_datetime(request.form.get("started_at"), entry.started_at)
    ended_at = parse_local_datetime(request.form.get("ended_at"), entry.ended_at or utc_now())
    if ended_at <= started_at:
        flash("Koniec sesji musi byc pozniejszy niz start.", "danger")
        return redirect(_tracking_redirect(project_id))

    entry.project = project
    entry.started_at = started_at
    entry.ended_at = ended_at
    entry.description = (request.form.get("description") or "").strip() or None

    try:
        db.session.commit()
        flash("Sesja czasu zostala zaktualizowana.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Nie udalo sie zapisac sesji czasu.", "danger")

    return redirect(_tracking_redirect(project_id))


@time_tracking_bp.route("/entries/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete_entry(entry_id):
    entry = ProjectTimeEntry.query.filter_by(id=entry_id, user_id=current_user.id).first_or_404()
    project_id = entry.project_id
    db.session.delete(entry)
    try:
        db.session.commit()
        flash("Sesja czasu zostala usunieta.", "info")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Nie udalo sie usunac sesji czasu.", "danger")
    return redirect(_tracking_redirect(project_id))


def _project_timer_payload(project, summary):
    active = summary["active_entry"]
    return {
        "ok": True,
        "project_id": project.id,
        "project_title": project.title,
        "project_url": url_for("projects.project_detail", project_id=project.id, open_timer=1),
        "today_seconds": summary["total_seconds"],
        "today_label": format_duration(summary["total_seconds"]),
        "is_running": active is not None,
        "started_at": active.started_at.isoformat() if active else None,
        "description": summary["active_description"],
        "day_description": summary["description"],
        "sessions": [_timer_session_payload(entry) for entry in summary["entries"]],
    }


def _timer_session_payload(entry):
    started_at = ensure_utc(entry.started_at).astimezone(app_timezone())
    ended_at = None
    if entry.ended_at:
        ended_at = ensure_utc(entry.ended_at).astimezone(app_timezone())
    return {
        "id": entry.id,
        "started_label": started_at.strftime("%H:%M"),
        "ended_label": ended_at.strftime("%H:%M") if ended_at else "teraz",
        "duration_label": format_duration(entry_elapsed_seconds(entry)),
        "description": entry.description or "",
        "is_running": entry.ended_at is None,
    }


def _tracking_redirect(project_id=None):
    args = {}
    selected_date_mode = request.form.get("selected_date_mode") or request.args.get("date_mode")
    selected_date = request.form.get("selected_date") or request.args.get("date")
    selected_project = request.form.get("selected_project_id") or request.args.get("project_id") or project_id
    if selected_date_mode == "all":
        args["date_mode"] = "all"
    elif selected_date:
        args["date"] = selected_date
    if selected_project:
        args["project_id"] = selected_project
    return url_for("time_tracking.index", **args)
