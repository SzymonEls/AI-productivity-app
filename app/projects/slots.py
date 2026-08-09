"""
Daily project slots: every day offers A, B and an optional C, each holding at
most one project.

This lives outside routes.py for the same reason app/time_tracking/service.py
does - it is date and timezone arithmetic, and "today" has to mean today in
CALENDAR_TIMEZONE rather than in UTC.
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Project, ProjectDaySlot
from ..time_tracking.service import app_timezone, utc_now


SLOTS = ("A", "B", "C")
# A and B are the day's real work; C is a spare that never shows tracked time.
TIMED_SLOTS = ("A", "B")
SCHEDULE_WINDOW_DAYS = 7


def today_local():
    """Today in CALENDAR_TIMEZONE, which is what a "day slot" is keyed on."""
    return utc_now().astimezone(app_timezone()).date()


def parse_slot_date(value):
    """
    Strict ISO date, or None.

    Not time_tracking's parse_local_date(): that one falls back to today when a
    value is missing or malformed, which is right for a report filter but wrong
    here - a typo in the request would silently book today's slot.
    """
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def slots_for_date(user_id, day):
    """Return {"A": ProjectDaySlot|None, "B": ..., "C": ...} for one day."""
    booked = (
        ProjectDaySlot.query.options(joinedload(ProjectDaySlot.project))
        .filter_by(user_id=user_id, slot_date=day)
        .all()
    )
    by_slot = {slot: None for slot in SLOTS}
    for entry in booked:
        if entry.slot in by_slot:
            by_slot[entry.slot] = entry
    return by_slot


def slots_from(user_id, start_day, end_day=None):
    """Every booked slot from ``start_day`` on, grouped by date.

    One query for the whole range; the calendar page and the planner modal both
    build on it instead of asking per day.
    """
    query = (
        ProjectDaySlot.query.options(joinedload(ProjectDaySlot.project))
        .filter(ProjectDaySlot.user_id == user_id, ProjectDaySlot.slot_date >= start_day)
    )
    if end_day is not None:
        query = query.filter(ProjectDaySlot.slot_date <= end_day)

    by_date = {}
    for entry in query.order_by(ProjectDaySlot.slot_date.asc(), ProjectDaySlot.slot.asc()).all():
        by_date.setdefault(entry.slot_date, {slot: None for slot in SLOTS})[entry.slot] = entry
    return by_date


def scheduled_days(user_id, start_day=None):
    """Days from ``start_day`` on that have at least one project booked."""
    start_day = today_local() if start_day is None else start_day
    return sorted(slots_from(user_id, start_day).items())


def unscheduled_projects(user_id):
    """
    Active projects with no slot *after* today.

    Deliberately excludes today: a project being worked on right now but with no
    next session still needs planning, so it belongs on this list.
    """
    today = today_local()
    planned = (
        db.session.query(ProjectDaySlot.project_id)
        .filter(ProjectDaySlot.user_id == user_id, ProjectDaySlot.slot_date > today)
        .distinct()
    )
    return (
        Project.query.filter(
            Project.user_id == user_id,
            Project.is_archived.is_(False),
            Project.id.notin_(planned),
        )
        .order_by(func.lower(Project.title).asc())
        .all()
    )


def project_bookings(user_id, project_id):
    """The project's slots from today on, as (today_slot, future_slot)."""
    today = today_local()
    entries = (
        ProjectDaySlot.query.filter(
            ProjectDaySlot.user_id == user_id,
            ProjectDaySlot.project_id == project_id,
            ProjectDaySlot.slot_date >= today,
        )
        .order_by(ProjectDaySlot.slot_date.asc())
        .all()
    )
    today_slot = next((entry for entry in entries if entry.slot_date == today), None)
    future_slot = next((entry for entry in entries if entry.slot_date > today), None)
    return today_slot, future_slot


def blocking_booking(user_id, project_id, day):
    """
    Why ``project_id`` may not take a slot on ``day``, or None if it may.

    A project gets at most two bookings: one today and one in the future.
    """
    today = today_local()
    today_slot, future_slot = project_bookings(user_id, project_id)

    if day == today:
        return today_slot
    return future_slot


def schedule_window(user_id, project_id, days=SCHEDULE_WINDOW_DAYS):
    """
    The planner grid: ``days`` days from today, each with its three slots and
    whether ``project_id`` could take them.

    Shaped for JSON so the modal can render it without a second request.
    """
    today = today_local()
    last_day = today + timedelta(days=days - 1)
    booked = slots_from(user_id, today, last_day)

    window = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        blocker = blocking_booking(user_id, project_id, day)
        day_slots = booked.get(day, {slot: None for slot in SLOTS})

        window.append(
            {
                "date": day.isoformat(),
                "label": day.strftime("%a %d %b"),
                "is_today": day == today,
                "slots": [
                    {
                        "slot": slot,
                        "project_id": day_slots[slot].project_id if day_slots[slot] else None,
                        "project_title": day_slots[slot].project.title if day_slots[slot] else "",
                        "is_this_project": bool(day_slots[slot]) and day_slots[slot].project_id == project_id,
                        "can_take": day_slots[slot] is None and blocker is None,
                    }
                    for slot in SLOTS
                ],
                # Same reason for all three slots of a day, so it is reported once.
                "blocked_reason": _blocked_reason(blocker, day, today),
            }
        )
    return window


def _blocked_reason(blocker, day, today):
    if blocker is None:
        return ""
    if day == today:
        return f"Already in today's slot {blocker.slot}."
    return f"Already planned for {blocker.slot_date.strftime('%d %b')} in slot {blocker.slot}."


def slot_candidates(user_id, day, slot):
    """
    Every active project, annotated with whether it can take this slot.

    Projects the two-block rule rules out are returned too, with the reason,
    rather than silently missing from the list - "where did that project go" is
    a worse experience than a greyed-out row that explains itself.
    """
    from ..time_tracking.service import first_plan_section_title, project_last_session_labels

    projects = (
        Project.query.filter_by(user_id=user_id, is_archived=False)
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    taken = ProjectDaySlot.query.filter_by(user_id=user_id, slot_date=day, slot=slot).first()
    labels = project_last_session_labels(user_id, projects)
    today = today_local()

    candidates = []
    for project in projects:
        if taken is not None:
            reason = f"Slot {slot} is taken by {taken.project.title}."
        else:
            reason = _blocked_reason(blocking_booking(user_id, project.id, day), day, today)

        candidates.append(
            {
                "id": project.id,
                "title": project.title,
                "plan_heading": first_plan_section_title(project.long_goal),
                "last_session": labels.get(project.id, ""),
                "is_starred": bool(project.is_starred),
                "can_take": not reason,
                "reason": reason,
            }
        )

    # Available ones first; the rest keep their alphabetical order underneath.
    candidates.sort(key=lambda entry: (not entry["can_take"],))
    return candidates


def assign_slot(user_id, project_id, day, slot):
    """
    Book a project into a slot.

    Returns ``(ok, message)``. The caller commits; validation failures leave the
    session untouched.
    """
    if slot not in SLOTS:
        return False, "Unknown slot."
    if day < today_local():
        return False, "That day is in the past."

    project = Project.query.filter_by(id=project_id, user_id=user_id).first()
    if project is None:
        return False, "Project not found."
    if project.is_archived:
        return False, "Archived projects cannot be scheduled."

    taken = ProjectDaySlot.query.filter_by(user_id=user_id, slot_date=day, slot=slot).first()
    if taken is not None:
        if taken.project_id == project_id:
            return True, "Already scheduled here."
        return False, f"Slot {slot} is taken by {taken.project.title}."

    blocker = blocking_booking(user_id, project_id, day)
    if blocker is not None:
        return False, _blocked_reason(blocker, day, today_local())

    db.session.add(
        ProjectDaySlot(user_id=user_id, project_id=project_id, slot_date=day, slot=slot)
    )
    return True, f"Scheduled in slot {slot}."


def set_session_done(user_id, project_id, day, done):
    """
    Flag the project's session on ``day`` as finished, or unfinished again.

    Returns ``(ok, message, is_done)``; the caller commits.
    """
    booking = ProjectDaySlot.query.filter_by(
        user_id=user_id, project_id=project_id, slot_date=day
    ).first()
    if booking is None:
        return False, "This project has no session today.", False

    booking.is_done = bool(done)
    return True, "Session marked done." if booking.is_done else "Session reopened.", booking.is_done


def clear_slot(user_id, day, slot):
    """Free a slot. Returns ``(ok, message)``; the caller commits."""
    if slot not in SLOTS:
        return False, "Unknown slot."

    booking = ProjectDaySlot.query.filter_by(user_id=user_id, slot_date=day, slot=slot).first()
    if booking is None:
        return True, "That slot is already free."

    db.session.delete(booking)
    return True, f"Slot {slot} cleared."
