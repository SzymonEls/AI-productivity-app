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
# The schedule page shows three rolling weeks of day cards, empty days included.
CALENDAR_WEEKS = 3
DAYS_PER_WEEK = 7


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


def calendar_weeks(user_id, weeks=CALENDAR_WEEKS, start_day=None):
    """
    The schedule page: ``weeks`` calendar weeks of days, as lists of
    ``(date, {slot: ProjectDaySlot|None})``.

    Weeks run Monday to Sunday. The first one starts today rather than on its
    Monday - days that have already passed cannot be booked, so there is nothing
    to show there - which makes it a short week on any day but a Monday.

    Empty days are kept: the page is a strip of calendar sheets you can book or
    drop a project onto, so a day with nothing in it is a target rather than
    something to leave out.
    """
    start_day = today_local() if start_day is None else start_day
    # Monday is weekday() 0, so this is 7 on a Monday and 1 on a Sunday.
    first_week_days = DAYS_PER_WEEK - start_day.weekday()
    total_days = first_week_days + (weeks - 1) * DAYS_PER_WEEK
    booked = slots_from(user_id, start_day, start_day + timedelta(days=total_days - 1))

    calendar = []
    day = start_day
    for index in range(weeks):
        length = first_week_days if index == 0 else DAYS_PER_WEEK
        calendar.append(
            [
                (
                    day + timedelta(days=offset),
                    booked.get(day + timedelta(days=offset), {slot: None for slot in SLOTS}),
                )
                for offset in range(length)
            ]
        )
        day += timedelta(days=length)
    return calendar


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


def project_bookings(user_id, project_id, ignore_ids=()):
    """The project's slots from today on, as (today_slot, future_slot).

    ``ignore_ids`` drops bookings that are on their way out - the row being
    dragged elsewhere, or the one about to be deleted. Without it a booking
    would count as its own blocker and no move could ever be legal.
    """
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
    entries = [entry for entry in entries if entry.id not in ignore_ids]
    today_slot = next((entry for entry in entries if entry.slot_date == today), None)
    future_slot = next((entry for entry in entries if entry.slot_date > today), None)
    return today_slot, future_slot


def bookings_by_project(user_id):
    """
    ``{project_id: (today_slot, future_slot)}`` for every booked project, in one
    query.

    The bulk form of project_bookings(). Asking per project is fine for one
    project, but the picker weighs the rule against the whole project list at
    once, and that turned into a query each.
    """
    today = today_local()
    entries = (
        ProjectDaySlot.query.filter(
            ProjectDaySlot.user_id == user_id, ProjectDaySlot.slot_date >= today
        )
        .order_by(ProjectDaySlot.slot_date.asc())
        .all()
    )

    by_project = {}
    for entry in entries:
        today_slot, future_slot = by_project.get(entry.project_id, (None, None))
        if entry.slot_date == today:
            today_slot = today_slot or entry
        elif future_slot is None:
            future_slot = entry
        by_project[entry.project_id] = (today_slot, future_slot)
    return by_project


def blocker_for_day(bookings, day, today=None):
    """
    Which of a project's two bookings stands in the way on ``day``, if any.

    ``bookings`` is a ``(today_slot, future_slot)`` pair from either
    project_bookings() or bookings_by_project() - the rule itself lives here, so
    both the single-project and the bulk path answer identically.
    """
    today_slot, future_slot = bookings
    return today_slot if day == (today or today_local()) else future_slot


def blocking_booking(user_id, project_id, day, ignore_ids=()):
    """
    Why ``project_id`` may not take a slot on ``day``, or None if it may.

    A project gets at most two bookings: one today and one in the future.
    """
    return blocker_for_day(project_bookings(user_id, project_id, ignore_ids), day)


def schedule_window(user_id, project_id, days=SCHEDULE_WINDOW_DAYS):
    """
    The planner grid: ``days`` days from today, each with its three slots and
    whether ``project_id`` could take them.

    Shaped for JSON so the modal can render it without a second request.
    """
    today = today_local()
    last_day = today + timedelta(days=days - 1)
    booked = slots_from(user_id, today, last_day)
    # The project's own two bookings do not change from day to day, so they are
    # read once for the whole grid rather than per row.
    bookings = project_bookings(user_id, project_id)

    window = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        blocker = blocker_for_day(bookings, day, today)
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
                        # The dialog colours a slot exactly like the home page does,
                        # so it needs the same two facts about it.
                        "is_done": bool(day_slots[slot]) and bool(day_slots[slot].is_done),
                        "is_optional": slot not in TIMED_SLOTS,
                    }
                    for slot in SLOTS
                ],
            }
        )
    return window


def booking_note(user_id, project_id):
    """
    Where this project already stands, as the one line the planner shows.

    The two-block rule blocks whole days at a time, so saying it per day - or
    once per booking - only repeats itself. One sentence names both bookings and
    the rule behind them, or nothing at all when the project is free to plan.
    """
    today_slot, future_slot = project_bookings(user_id, project_id)

    booked = []
    if today_slot is not None:
        booked.append(f"today in slot {today_slot.slot}")
    if future_slot is not None:
        booked.append(f"{future_slot.slot_date.strftime('%d %b')} in slot {future_slot.slot}")
    if not booked:
        return ""

    return (
        f"Already planned for {' and '.join(booked)} — "
        "a project takes at most one block today and one later."
    )


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
    # Every project is weighed against the rule here, so their bookings come in
    # one query instead of one per row.
    bookings = bookings_by_project(user_id) if taken is None else {}

    candidates = []
    for project in projects:
        if taken is not None:
            reason = f"Slot {slot} is taken by {taken.project.title}."
        else:
            blocker = blocker_for_day(bookings.get(project.id, (None, None)), day, today)
            reason = _blocked_reason(blocker, day, today)

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


def move_booking(user_id, from_day, from_slot, to_day, to_slot):
    """
    Move a booking to another day and slot, swapping with whatever sits there.

    This is what a drag on the schedule page ends in. Returns ``(ok, message)``;
    the caller commits, and a rejected move leaves the session untouched.
    """
    today = today_local()

    if from_slot not in SLOTS or to_slot not in SLOTS:
        return False, "Unknown slot."
    if from_day < today or to_day < today:
        return False, "That day is in the past."

    source = ProjectDaySlot.query.filter_by(
        user_id=user_id, slot_date=from_day, slot=from_slot
    ).first()
    if source is None:
        return False, "There is nothing to move."
    if from_day == to_day and from_slot == to_slot:
        return True, "Nothing moved."

    target = ProjectDaySlot.query.filter_by(user_id=user_id, slot_date=to_day, slot=to_slot).first()
    moves = [(source, to_day)]
    if target is not None:
        moves.append((target, from_day))

    # Both rows are leaving their current spot, so neither may count as a
    # blocker - for itself or for the other one - while the rule is checked.
    ignore_ids = {entry.id for entry, _ in moves}
    for entry, day in moves:
        blocker = blocking_booking(user_id, entry.project_id, day, ignore_ids)
        if blocker is not None:
            return False, f"{entry.project.title}: {_blocked_reason(blocker, day, today)}"

    # Updating both rows in one flush would collide with the unique constraint on
    # (user, date, slot), so the displaced row leaves the table and comes back on
    # the spot the moved one has just vacated.
    # Read off what the displaced row has to say before deleting it.
    displaced = (target.project_id, target.is_done, target.project.title) if target is not None else None
    if target is not None:
        db.session.delete(target)
        db.session.flush()

    # "Done" describes a day's session, so it travels within a day and is
    # dropped when the booking lands on another date.
    source.slot_date = to_day
    source.slot = to_slot
    if to_day != from_day:
        source.is_done = False
    db.session.flush()

    if displaced is not None:
        project_id, was_done, displaced_title = displaced
        db.session.add(
            ProjectDaySlot(
                user_id=user_id,
                project_id=project_id,
                slot_date=from_day,
                slot=from_slot,
                is_done=was_done if to_day == from_day else False,
            )
        )
        return True, f"Swapped with {displaced_title}."

    return True, f"Moved to {to_day.strftime('%d %b')}, slot {to_slot}."


def clear_slot(user_id, day, slot):
    """Free a slot. Returns ``(ok, message)``; the caller commits."""
    if slot not in SLOTS:
        return False, "Unknown slot."

    booking = ProjectDaySlot.query.filter_by(user_id=user_id, slot_date=day, slot=slot).first()
    if booking is None:
        return True, "That slot is already free."

    db.session.delete(booking)
    return True, f"Slot {slot} cleared."
