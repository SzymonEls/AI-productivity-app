from collections import defaultdict
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from flask import current_app

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
