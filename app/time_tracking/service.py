from collections import defaultdict
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import func

from ..models import ProjectTimeEntry


def app_timezone():
    timezone_name = current_app.config.get("CALENDAR_TIMEZONE", "Europe/Warsaw")
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("Europe/Warsaw")


def utc_now():
    return datetime.now(timezone.utc)


def ensure_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_local_date(value, default=None):
    if not value:
        return default or date.today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default or date.today()


def parse_local_datetime(value, fallback):
    if not value:
        return fallback

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return fallback

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=app_timezone())
    return parsed.astimezone(timezone.utc)


def day_bounds_utc(day):
    tz = app_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day, time.max, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def local_datetime_value(value):
    if not value:
        return ""
    return ensure_utc(value).astimezone(app_timezone()).strftime("%Y-%m-%dT%H:%M")


def format_duration(total_seconds):
    total_seconds = max(int(total_seconds or 0), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def entry_elapsed_seconds(entry, now=None):
    now = ensure_utc(now or utc_now())
    started_at = ensure_utc(entry.started_at)
    ended_at = ensure_utc(entry.ended_at) or now
    return max(int((ended_at - started_at).total_seconds()), 0)


def entry_overlap_seconds(entry, range_start, range_end, now=None):
    now = ensure_utc(now or utc_now())
    started_at = ensure_utc(entry.started_at)
    ended_at = ensure_utc(entry.ended_at) or now
    overlap_start = max(started_at, ensure_utc(range_start))
    overlap_end = min(ended_at, ensure_utc(range_end))
    return max(int((overlap_end - overlap_start).total_seconds()), 0)


def entries_for_range(user_id, range_start, range_end, project_id=None):
    query = ProjectTimeEntry.query.filter(
        ProjectTimeEntry.user_id == user_id,
        ProjectTimeEntry.started_at <= range_end,
    ).filter(
        (ProjectTimeEntry.ended_at.is_(None)) | (ProjectTimeEntry.ended_at >= range_start)
    )
    if project_id:
        query = query.filter(ProjectTimeEntry.project_id == project_id)
    return query.order_by(ProjectTimeEntry.started_at.desc()).all()


def first_plan_section_title(markdown):
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if line.startswith("# ") and stripped[2:].strip():
            return stripped[2:].strip()
    return ""


def active_entry_for_user(user_id):
    return (
        ProjectTimeEntry.query.filter_by(user_id=user_id, ended_at=None)
        .order_by(ProjectTimeEntry.started_at.desc())
        .first()
    )


def today_project_summary(user_id, project_id):
    today = datetime.now(app_timezone()).date()
    range_start, range_end = day_bounds_utc(today)
    entries = entries_for_range(user_id, range_start, range_end, project_id=project_id)
    now = utc_now()
    total_seconds = sum(entry_overlap_seconds(entry, range_start, range_end, now) for entry in entries)
    active_entry = next((entry for entry in entries if entry.ended_at is None), None)
    descriptions = [entry.description.strip() for entry in entries if entry.description and entry.description.strip()]
    return {
        "date": today,
        "entries": entries,
        "total_seconds": total_seconds,
        "active_entry": active_entry,
        "active_description": active_entry.description if active_entry and active_entry.description else "",
        "description": "\n\n".join(reversed(descriptions)),
    }


def daily_totals_by_project(user_id, day):
    range_start, range_end = day_bounds_utc(day)
    entries = entries_for_range(user_id, range_start, range_end)
    totals = defaultdict(int)
    now = utc_now()
    for entry in entries:
        totals[entry.project_id] += entry_overlap_seconds(entry, range_start, range_end, now)
    return totals


def project_last_session_labels(user_id, projects):
    project_ids = [project.id for project in projects]
    if not project_ids:
        return {}

    last_sessions = dict(
        ProjectTimeEntry.query.with_entities(ProjectTimeEntry.project_id, func.max(ProjectTimeEntry.started_at))
        .filter(ProjectTimeEntry.user_id == user_id, ProjectTimeEntry.project_id.in_(project_ids))
        .group_by(ProjectTimeEntry.project_id)
        .all()
    )

    now = utc_now()
    return {
        project.id: human_last_session_label(last_sessions.get(project.id), now)
        for project in projects
    }


def human_last_session_label(value, now):
    if not value:
        return "Last session: none"

    timestamp = ensure_utc(value)
    seconds = int(max((now - timestamp).total_seconds(), 0))

    if seconds < 60:
        return "Last session: just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"Last session: {minutes} min ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"Last session: {hours} hr ago"
    if seconds < 172800:
        return "Last session: yesterday"
    if seconds < 604800:
        days = seconds // 86400
        return f"Last session: {days} days ago"
    if seconds < 1209600:
        return "Last session: a week ago"
    if seconds < 2592000:
        weeks = seconds // 604800
        return f"Last session: {weeks} wk ago"
    if seconds < 31536000:
        months = seconds // 2592000
        return f"Last session: {months} mo ago"

    years = seconds // 31536000
    return "Last session: a year ago" if years == 1 else f"Last session: {years} years ago"
