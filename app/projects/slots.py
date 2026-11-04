"""
Daily project slots: every day offers A, B and an optional C, each holding at
most one project.

This lives outside routes.py for the same reason app/time_tracking/service.py
does - it is date and timezone arithmetic, and "today" has to mean today in
CALENDAR_TIMEZONE rather than in UTC.
"""

from datetime import date, timedelta

from flask import g, has_app_context
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Project, ProjectDaySlot
from ..time_tracking.service import app_timezone, ensure_utc, tracked_seconds_by_day, utc_now


SLOTS = ("A", "B", "C")
# A and B are the day's real work; C is a spare that never shows tracked time.
TIMED_SLOTS = ("A", "B")
# The planner dialog offers a fortnight: a week was short enough that a project
# with a booking in it had nowhere left to go, and the dialog scrolls anyway.
SCHEDULE_WINDOW_DAYS = 14
DAYS_PER_WEEK = 7
# The schedule page shows a month of rolling weeks of day cards, empty days
# included - five, because the first week starts today rather than on its Monday.
SCHEDULE_WEEKS = 5
# The archive pages back through the same sheets three weeks at a time. Shorter
# than the schedule on purpose: it is read backwards, a page at a time, and every
# page costs a click.
ARCHIVE_WEEKS = 3
# The schedule page grows past its default when the bookings run further out - a
# day off pushes them - but not without end: past this it is a scroll through
# empty sheets.
MAX_CALENDAR_WEEKS = 12
# The calendar view of the schedule loads further weeks as it is scrolled
# rather than by link, so it can afford to reach further than the sheets do -
# but a year ahead is where the scroll stops: nothing is planned that far out.
MAX_SCROLL_WEEKS = 52

# What a project may ask for as its fewest sessions a week. At most one block a
# day goes to a project, so seven is as many as a week can hold.
MIN_SESSIONS_PER_WEEK = 1
MAX_SESSIONS_PER_WEEK = 7

# The health score on the home page: the last week of finished sessions, and
# nothing else. It measures the bookings that were actually made - A, B and C
# alike - so an empty slot is neither a session missed nor one to make up for.
# Planning deliberately stays out of it: every project is meant to have a next
# session booked, so having done that is the baseline rather than an achievement,
# and paying for it put a floor under the score that a week of missed sessions
# could not break through. The "Not scheduled" list on the home page is where
# planning shows.
# The window ends yesterday. Today is still being worked on, and counting its
# bookings would open every morning with a drop that the day then undoes.
HEALTH_WINDOW_DAYS = 7
# Below these the ring turns amber and then red.
HEALTH_GOOD_PERCENT = 75
HEALTH_WARN_PERCENT = 50
# How far back the health chart on the home page goes: the score as it stood on
# each of the last fifteen mornings, so the first point is a full two weeks
# before today's and the line shows what the fortnight did to it.
HEALTH_HISTORY_DAYS = 15

# How far back the Statistics widget on a project page looks. Three weeks is long
# enough that one skipped week does not halve the average and short enough that
# it still describes how the project is going now rather than how it went.
STATISTICS_WEEKS = 3


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


def deadline_label(day):
    """A deadline as the blocks print it: "14 Oct" - short enough to stand on end."""
    return f"{day.day} {day.strftime('%b')}"


def deadline_time_label(project):
    """The deadline's hour as "14:30", or "" for a deadline that is a whole day."""
    if project is None or project.session_deadline_time is None:
        return ""
    return project.session_deadline_time.strftime("%H:%M")


def last_session_day(project):
    """The last day the project's next session may happen on, or None.

    The deadline itself, or the day before it when the project asks for its
    session "at least a day before". Everything that decides whether a session
    is late asks this rather than reading the deadline.
    """
    if project is None or project.session_deadline is None:
        return None
    if project.session_deadline_day_before:
        return project.session_deadline - timedelta(days=1)
    return project.session_deadline


# What the select on the project page offers, and how each choice is spelled
# out after the deadline wherever it is named.
DEADLINE_RULE_SAME_DAY = "same_day"
DEADLINE_RULE_DAY_BEFORE = "day_before"
DEADLINE_RULE_LABELS = {
    DEADLINE_RULE_SAME_DAY: "On the deadline day at the latest",
    DEADLINE_RULE_DAY_BEFORE: "At least a day before",
}


def deadline_rule_note(project):
    """"session a day before" for a project that asks for it, otherwise ""."""
    if project is None or not project.session_deadline_day_before:
        return ""
    return "session at least a day before"


def project_deadline_label(project):
    """A project's deadline in words: "14 Oct", or "14 Oct 14:30" with an hour.

    A deadline that wants its session a day early says so after the date -
    "14 Oct, session at least a day before" - since every place that names it
    (a tooltip, a warning, the question before a late booking) is also saying
    why a day counts as late.
    """
    if project is None or project.session_deadline is None:
        return ""
    time_label = deadline_time_label(project)
    label = deadline_label(project.session_deadline)
    label = f"{label} {time_label}" if time_label else label
    note = deadline_rule_note(project)
    return f"{label}, {note}" if note else label


def is_after_deadline(project, day):
    """Whether a session of ``project`` on ``day`` would come too late.

    Late means after ``last_session_day``: on the deadline day itself for a
    project that wants its session a day before, and only past it otherwise.
    """
    last_day = last_session_day(project)
    return last_day is not None and day > last_day


def deadline_warning(project, day):
    """What booking ``project`` on ``day`` should be warned about, or "".

    A warning and never a refusal: a deadline is a plan, and a plan that has
    slipped still needs its session booked somewhere.
    """
    if not is_after_deadline(project, day):
        return ""
    return (
        f"{project.title} is now planned after its session deadline "
        f"({project_deadline_label(project)})."
    )


def deadlines_by_day(user_id, first_day, last_day):
    """``{day: [project, ...]}`` for the deadlines from ``first_day`` to ``last_day``.

    Keyed by the deadline itself rather than by the last session day: the
    schedule's D marks the day something is due. Archived projects are left
    out, the way they are out of every list of what is still to be done.
    """
    projects = (
        Project.query.filter(
            Project.user_id == user_id,
            Project.is_archived.is_(False),
            Project.session_deadline.isnot(None),
            Project.session_deadline >= first_day,
            Project.session_deadline <= last_day,
        )
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    found = {}
    for project in projects:
        found.setdefault(project.session_deadline, []).append(project)
    return found


def meet_deadline(booking):
    """A session ticked done meets its project's deadline, which then goes.

    The deadline is about the next session, so the one that has just happened
    is the one it was for. Reopening the session does not bring it back.

    It is also the way out of being problematic: one session that did happen
    is what the flag was waiting for, and it is not brought back either.
    """
    if booking.is_done and booking.project is not None:
        booking.project.session_deadline = None
        booking.project.session_deadline_time = None
        booking.project.session_deadline_day_before = False
        booking.project.is_problematic = False


# What the ! says on hover for a problematic project, on the board and on the
# home page alike. The board's script spells the same out after a move
# (schedule-board.js), along with the frequency title below.
PROBLEMATIC_TITLE = "Problematic project — a session of it failed"


def allowed_gap_days(project):
    """The most days one session may come after the one before: 7 / sessions a week.

    A float on purpose - twice a week allows 3.5 days, so a gap of 4 is late and
    3 is not.
    """
    per_week = (project.sessions_per_week if project is not None else None) or 1
    per_week = max(MIN_SESSIONS_PER_WEEK, min(per_week, MAX_SESSIONS_PER_WEEK))
    return DAYS_PER_WEEK / per_week


def _session_history(user_id):
    """``{project_id: [(booking_id, day, is_done, is_failed), ...]}`` for a user.

    Every booking there has ever been, read once per request: a schedule page
    weighs each of its blocks against the ones before it, and asking per block
    would be a query each. Kept on ``g`` for the request only - nothing that
    changes a booking renders a block afterwards in the same request.
    """
    cache = getattr(g, "_session_history", None) if has_app_context() else None
    if cache is not None and user_id in cache:
        return cache[user_id]

    rows = (
        db.session.query(
            ProjectDaySlot.id,
            ProjectDaySlot.project_id,
            ProjectDaySlot.slot_date,
            ProjectDaySlot.is_done,
            ProjectDaySlot.is_failed,
        )
        .filter(ProjectDaySlot.user_id == user_id)
        .all()
    )
    history = {}
    for booking_id, project_id, day, is_done, is_failed in rows:
        history.setdefault(project_id, []).append((booking_id, day, bool(is_done), bool(is_failed)))

    if has_app_context():
        if cache is None:
            cache = g._session_history = {}
        cache[user_id] = history
    return history


def _counts_as_session(day, is_done, is_failed, today):
    """Whether a booking is a session the next one is measured from.

    A done one always is. One still to come - today or later, not failed -
    is too, since it is planned to happen. A past one never ticked off is not:
    as far as the app knows, it did not happen.
    """
    return is_done or (day >= today and not is_failed)


def project_created_day(project):
    """The day a project was created, in CALENDAR_TIMEZONE."""
    return ensure_utc(project.created_at).astimezone(app_timezone()).date()


def previous_session(booking, today=None):
    """``(day, is_creation)``: what ``booking`` is measured from.

    The latest session of the project before the booking's day - done, or
    planned and still to come - or, for a project with none, the day it was
    created, so a new project's first session is held to the same rhythm.
    """
    today = today or today_local()
    project = booking.project
    days = [
        day
        for booking_id, day, is_done, is_failed in _session_history(booking.user_id).get(project.id, ())
        if booking_id != booking.id
        and day < booking.slot_date
        and _counts_as_session(day, is_done, is_failed, today)
    ]
    if days:
        return max(days), False
    return project_created_day(project), True


def frequency_gap(booking, today=None):
    """``(days, previous_day, is_creation)`` for an open booked session, or None.

    None for anything that is not a session still to happen: a free block, a
    done one, a failed one.
    """
    if booking is None or booking.project is None or booking.is_done or booking.is_failed:
        return None
    previous_day, is_creation = previous_session(booking, today)
    return (booking.slot_date - previous_day).days, previous_day, is_creation


def is_behind_frequency(booking, today=None):
    """Whether the session comes too long after the one before it.

    Too long is more than ``allowed_gap_days``: with one session a week, a
    session eight days after the last one is late and one seven days after is
    not. Moving a session about is free until it crosses that line.
    """
    gap = frequency_gap(booking, today)
    return gap is not None and gap[0] > allowed_gap_days(booking.project)


def sessions_per_week_label(count):
    return f"{count} session a week" if count == 1 else f"{count} sessions a week"


def frequency_title(booking, today=None):
    """What the ! says for a session behind the project's minimum frequency."""
    gap = frequency_gap(booking, today)
    if gap is None:
        return ""
    days, previous_day, is_creation = gap
    since = "the project was created" if is_creation else "the session before"
    return (
        f"Below {sessions_per_week_label(booking.project.sessions_per_week or 1)} — "
        f"{days} days after {since} ({deadline_label(previous_day)})"
    )


def session_before_today(project, user_id, today=None):
    """``(day, is_creation)``: the last session before today, or the creation day.

    What the board's script measures a moved session from, together with the
    project's sessions still on the board (today and later), which it can see
    for itself.
    """
    today = today or today_local()
    days = [
        day
        for _, day, is_done, _ in _session_history(user_id).get(project.id, ())
        if day < today and is_done
    ]
    if days:
        return max(days), False
    return project_created_day(project), True


def warn_level(booking):
    """1 when a session still to come is flagged red with a "!", otherwise 0.

    Two things flag it, and nothing else: its project is problematic (a session
    of it failed), or the session comes so long after the one before that the
    project falls below its sessions a week. Moving a session is free until it
    crosses that line. A session that has ended - done or failed - is never
    flagged, since nothing about it is late any more.
    """
    if booking is None or booking.project is None or booking.is_done or booking.is_failed:
        return 0
    if booking.project.is_problematic or is_behind_frequency(booking):
        return 1
    return 0


def warn_title(booking):
    """What a session's ! means: its project is problematic, or it is behind."""
    if not warn_level(booking):
        return ""
    if booking.project.is_problematic:
        return PROBLEMATIC_TITLE
    return frequency_title(booking)


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


def calendar_weeks(user_id, weeks=SCHEDULE_WEEKS, start_day=None):
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


def past_calendar_weeks(user_id, weeks=ARCHIVE_WEEKS, end_day=None):
    """
    The archive: ``weeks`` calendar weeks up to and including ``end_day``
    (yesterday by default), newest week first.

    The mirror image of calendar_weeks(). There the first week is the short one,
    because it starts today; here it is the newest, because it ends on ``end_day``
    - every other week runs Monday to Sunday in full. Days keep their calendar
    order inside a week; only the weeks are reversed, so the page opens on what
    happened most recently.
    """
    end_day = today_local() - timedelta(days=1) if end_day is None else end_day
    # Monday is weekday() 0, so this is 1 on a Monday and 7 on a Sunday.
    newest_week_days = end_day.weekday() + 1
    total_days = newest_week_days + (weeks - 1) * DAYS_PER_WEEK
    booked = slots_from(user_id, end_day - timedelta(days=total_days - 1), end_day)

    calendar = []
    last_day = end_day
    for index in range(weeks):
        length = newest_week_days if index == 0 else DAYS_PER_WEEK
        monday = last_day - timedelta(days=length - 1)
        calendar.append(
            [
                (
                    monday + timedelta(days=offset),
                    booked.get(monday + timedelta(days=offset), {slot: None for slot in SLOTS}),
                )
                for offset in range(length)
            ]
        )
        last_day = monday - timedelta(days=1)
    return calendar


def first_booked_day(user_id):
    """The earliest day this user ever booked, or None if they never have.

    The archive stops there rather than paging back through empty weeks forever.
    """
    return (
        db.session.query(func.min(ProjectDaySlot.slot_date))
        .filter(ProjectDaySlot.user_id == user_id)
        .scalar()
    )


def last_booked_day(user_id):
    """The latest day this user has booked, or None if they never have.

    The mirror of first_booked_day(): the archive stops at the earliest booking,
    the schedule page reaches out to the latest one.
    """
    return (
        db.session.query(func.max(ProjectDaySlot.slot_date))
        .filter(ProjectDaySlot.user_id == user_id)
        .scalar()
    )


def weeks_to_cover(user_id, start_day=None, minimum=SCHEDULE_WEEKS, maximum=MAX_CALENDAR_WEEKS):
    """How many calendar weeks the schedule has to show to reach the last booking.

    The page shows a fixed number of weeks by default, which is fine until
    something pushes a booking past its edge - taking a day off does exactly
    that. The window then grows to the last booked day rather than hiding it,
    up to ``maximum`` weeks.
    """
    start_day = today_local() if start_day is None else start_day
    last = last_booked_day(user_id)
    if last is None or last <= start_day:
        return minimum

    # The first week is the short one: it starts today rather than on its Monday.
    first_week_days = DAYS_PER_WEEK - start_day.weekday()
    days_needed = (last - start_day).days + 1
    if days_needed <= first_week_days:
        weeks = 1
    else:
        # Ceiling division over the whole weeks that follow the short one.
        weeks = 1 + -(-(days_needed - first_week_days) // DAYS_PER_WEEK)
    return max(minimum, min(weeks, maximum))


def unscheduled_projects(user_id):
    """
    Active projects with no slot *after* today.

    Deliberately excludes today: a project being worked on right now but with no
    next session still needs planning, so it belongs on this list.

    A project waiting for another one is left off too: there is no next session
    to plan until the milestone it waits for is reached, so listing it would
    only be a reminder nobody can act on.
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
            Project.waiting_for_project_id.is_(None),
            Project.id.notin_(planned),
        )
        .order_by(func.lower(Project.title).asc())
        .all()
    )


def session_counts_since(user_id, first_day, last_day):
    """``(booked, done)`` slots between the two dates, inclusive.

    Both halves come from one pass over the range: "done" is only ever a share
    of what was booked, so the two numbers are never wanted apart.
    """
    booked, done = (
        db.session.query(
            func.count(ProjectDaySlot.id),
            # count() skips the NULLs the case leaves for the unfinished ones.
            func.count(case((ProjectDaySlot.is_done.is_(True), 1))),
        )
        .filter(
            ProjectDaySlot.user_id == user_id,
            ProjectDaySlot.slot_date >= first_day,
            ProjectDaySlot.slot_date <= last_day,
        )
        .one()
    )
    return booked or 0, done or 0


def _health_percent(booked, done):
    # A week with nothing booked scores zero rather than full marks: there is no
    # completion rate to read off it, and an empty week is not a healthy one.
    return round(done / booked * 100) if booked else 0


def _health_level(percent):
    if percent >= HEALTH_GOOD_PERCENT:
        return "good"
    if percent >= HEALTH_WARN_PERCENT:
        return "warn"
    return "bad"


def system_health(user_id):
    """
    One 0-100 figure for "is the work getting done".

    The score is the sessions alone: of the sessions booked over the week before
    today, how many were ticked off. Only booked slots count, in A, B and C
    alike - a slot nobody filled was never a session to miss, so leaving one
    empty neither helps nor hurts. Today is left out entirely, so the score only
    falls in the morning if yesterday was left unfinished. Planning scores
    nothing; see the note on HEALTH_WINDOW_DAYS.
    """
    today = today_local()
    yesterday = today - timedelta(days=1)
    booked, done = session_counts_since(
        user_id, yesterday - timedelta(days=HEALTH_WINDOW_DAYS - 1), yesterday
    )
    percent = _health_percent(booked, done)

    return {
        "percent": percent,
        "level": _health_level(percent),
        "window_days": HEALTH_WINDOW_DAYS,
        "done_sessions": done,
        "booked_sessions": booked,
    }


def health_history(user_id, days=HEALTH_HISTORY_DAYS):
    """The health score as it stood on each of the last ``days`` days, oldest first.

    Each day's score is worked out the way ``system_health`` works out today's:
    the week of sessions before that day. It is read off the bookings as they
    are now, so a session ticked off late counts on the days after it was due,
    the same as it does in today's score.

    One query for the whole stretch, counted per day; the overlapping weeks are
    then summed here rather than asked for one by one.
    """
    today = today_local()
    first_day = today - timedelta(days=days - 1)
    window_start = first_day - timedelta(days=HEALTH_WINDOW_DAYS)
    yesterday = today - timedelta(days=1)

    rows = (
        db.session.query(
            ProjectDaySlot.slot_date,
            func.count(ProjectDaySlot.id),
            func.count(case((ProjectDaySlot.is_done.is_(True), 1))),
        )
        .filter(
            ProjectDaySlot.user_id == user_id,
            ProjectDaySlot.slot_date >= window_start,
            ProjectDaySlot.slot_date <= yesterday,
        )
        .group_by(ProjectDaySlot.slot_date)
        .all()
    )
    per_day = {slot_date: (booked, done) for slot_date, booked, done in rows}

    history = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        booked = done = 0
        for back in range(1, HEALTH_WINDOW_DAYS + 1):
            day_booked, day_done = per_day.get(day - timedelta(days=back), (0, 0))
            booked += day_booked
            done += day_done
        percent = _health_percent(booked, done)
        history.append(
            {
                "date": day.isoformat(),
                "label": "Today" if day == today else day.strftime("%a %d"),
                "percent": percent,
                "level": _health_level(percent),
                "booked": booked,
                "done": done,
            }
        )
    return history


def project_statistics(user_id, project_id, weeks=STATISTICS_WEEKS):
    """How one project has actually been going over the last few weeks.

    A session here is a *day the project was worked on*: a booking ticked off,
    or time on the clock, or both. Counting only the ticked bookings would score
    a zero for someone who works from the timer and never marks the block done,
    and counting only the tracked time would lose the sessions that were done
    away from the keyboard - so a day counts once if either says so.

    Time comes from the timer alone, since a booking says nothing about how long
    it took. A session with nothing tracked therefore averages in as zero, which
    is what "average time spent on a session" has to mean when some of them were
    never timed.

    The window ends today rather than yesterday - unlike system_health(), which
    would open every morning with a drop. Nothing here is a score to fall, and
    the session you just finished belongs in it.
    """
    today = today_local()
    days = weeks * DAYS_PER_WEEK
    first_day = today - timedelta(days=days - 1)

    done_days = {
        slot_date
        for (slot_date,) in db.session.query(ProjectDaySlot.slot_date)
        .filter(
            ProjectDaySlot.user_id == user_id,
            ProjectDaySlot.project_id == project_id,
            ProjectDaySlot.is_done.is_(True),
            ProjectDaySlot.slot_date >= first_day,
            ProjectDaySlot.slot_date <= today,
        )
        .distinct()
    }
    tracked_days = tracked_seconds_by_day(user_id, project_id, first_day, today)

    session_days = done_days | set(tracked_days)
    session_count = len(session_days)
    tracked_seconds = sum(tracked_days.get(day, 0) for day in session_days)

    return {
        "weeks": weeks,
        "window_days": days,
        "first_day": first_day,
        "last_day": today,
        "sessions": session_count,
        "sessions_per_week": session_count / weeks,
        "tracked_seconds": tracked_seconds,
        "average_seconds": tracked_seconds // session_count if session_count else 0,
    }


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
    project = Project.query.filter_by(id=project_id, user_id=user_id).first()

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
                # Still bookable - the dialog only marks the days as late.
                "after_deadline": is_after_deadline(project, day),
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


def _booking_labels(bookings):
    """A ``(today_slot, future_slot)`` pair named: ``["today in slot A", ...]``.

    Empty when nothing is booked. The planner's note, the banner on an archived
    project and the archived list all say the same thing about the same two
    bookings, so they word it in one place.
    """
    today_slot, future_slot = bookings

    labels = []
    if today_slot is not None:
        labels.append(f"today in slot {today_slot.slot}")
    if future_slot is not None:
        labels.append(f"{future_slot.slot_date.strftime('%d %b')} in slot {future_slot.slot}")
    return labels


def planned_session_labels(user_id, project_id):
    """What this project still has booked from today on, as named sessions."""
    return _booking_labels(project_bookings(user_id, project_id))


def planned_session_labels_by_project(user_id):
    """``{project_id: ["today in slot A", ...]}`` for every booked project.

    The bulk form of planned_session_labels(), on bookings_by_project() rather
    than a query per project - the archived list asks this of a whole page of
    projects at once.
    """
    return {
        project_id: _booking_labels(bookings)
        for project_id, bookings in bookings_by_project(user_id).items()
    }


def booking_note(user_id, project_id):
    """
    Where this project already stands, as the one line the planner shows.

    The two-block rule blocks whole days at a time, so saying it per day - or
    once per booking - only repeats itself. One sentence names both bookings and
    the rule behind them, or nothing at all when the project is free to plan.
    """
    booked = planned_session_labels(user_id, project_id)
    project = Project.query.filter_by(id=project_id, user_id=user_id).first()
    deadline = (
        f"Session deadline: {project_deadline_label(project)}."
        if project is not None and project.session_deadline is not None
        else ""
    )
    if not booked:
        return deadline

    return " ".join(
        part
        for part in (
            f"Already planned for {' and '.join(booked)} — "
            "a project takes at most one block today and one later.",
            deadline,
        )
        if part
    )


def _blocked_reason(blocker, day, today):
    if blocker is None:
        return ""
    if day == today:
        return f"Already in today's slot {blocker.slot}."
    return f"Already planned for {blocker.slot_date.strftime('%d %b')} in slot {blocker.slot}."


def slot_candidates(user_id, day, slot):
    """
    Every active project not waiting for another one, annotated with whether it
    can take this slot.

    Projects the two-block rule rules out are returned too, with the reason,
    rather than silently missing from the list - "where did that project go" is
    a worse experience than a greyed-out row that explains itself.
    """
    from ..time_tracking.service import first_plan_section_title, project_last_session_labels

    # A project waiting for another one is left out too: until the milestone is
    # reached there is no session to offer it. Its own page can still book one.
    projects = (
        Project.query.filter_by(user_id=user_id, is_archived=False, waiting_for_project_id=None)
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
                # Bookable all the same; the picker says it would be late, and
                # asks before booking it.
                "deadline_warning": (
                    f"Past its deadline ({project_deadline_label(project)})"
                    if is_after_deadline(project, day)
                    else ""
                ),
                "deadline_label": project_deadline_label(project),
            }
        )

    # Available ones first; the rest keep their alphabetical order underneath.
    candidates.sort(key=lambda entry: (not entry["can_take"],))
    return candidates


def postponement_after(count, from_day, to_day):
    """The block's postponement count once it has moved from one day to another.

    Later is one step on, earlier is one step back, and a move inside the same
    sheet - dragging a session from block A to block B - is not a move in time
    at all, so it leaves the count alone.

    Only a record now: the count no longer colours or marks the block - the
    project's sessions a week decide that (``warn_level``). The floor at zero is
    the one bound, since a session can hardly be earlier than never late.
    """
    if to_day > from_day:
        return count + 1
    if to_day < from_day:
        return max(count - 1, 0)
    return count


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
    if booking.is_done:
        booking.is_failed = False
    meet_deadline(booking)
    return True, "Session marked done." if booking.is_done else "Session reopened.", booking.is_done


def set_session_failed(user_id, project_id, day, failed):
    """
    Mark the project's session on ``day`` as failed, or take that back.

    The alternative to done: the session was meant to happen and did not work
    out. Failing it marks the project problematic; taking it back reopens the
    session but leaves the flag alone - it is cleared by a session done, or by
    hand in the project's settings.

    Returns ``(ok, message, is_failed)``; the caller commits.
    """
    booking = ProjectDaySlot.query.filter_by(
        user_id=user_id, project_id=project_id, slot_date=day
    ).first()
    if booking is None:
        return False, "This project has no session today.", False

    booking.is_failed = bool(failed)
    if booking.is_failed:
        booking.is_done = False
        booking.project.is_problematic = True
        return True, "Session marked failed — the project is now problematic.", True
    return True, "Session reopened.", False


def set_block_done(user_id, day, slot, done):
    """
    Tick off the session booked in one block, or reopen it, on any day.

    The block rather than the project: this is what the archive ticks, where a
    day holds three finished sessions and "which project" is not the question -
    and where the same project may well have been booked again since.

    Returns ``(ok, message, is_done)``; the caller commits.
    """
    if slot not in SLOTS:
        return False, "Unknown slot.", False

    booking = ProjectDaySlot.query.filter_by(user_id=user_id, slot_date=day, slot=slot).first()
    if booking is None:
        return False, "That block is free.", False

    booking.is_done = bool(done)
    if booking.is_done:
        booking.is_failed = False
    meet_deadline(booking)
    return (
        True,
        "Session marked done." if booking.is_done else "Session reopened.",
        booking.is_done,
    )


def move_booking(user_id, from_day, from_slot, to_day, to_slot):
    """
    Move a booking to another day and slot, swapping with whatever sits there.

    This is what a drag on the schedule page ends in. Returns ``(ok, message)``;
    the caller commits, and a rejected move leaves the session untouched.

    Both sessions in a swap change date, so both have their postponement count
    brought up to date - in opposite directions, since they pass each other.
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
    # Read off what the displaced row has to say before deleting it. Its
    # postponement count comes back with it: the row is rebuilt only to get round
    # the constraint, and as far as the plan is concerned that session was moved,
    # not deleted and booked again.
    displaced = (
        (
            target.project_id,
            target.is_done,
            target.is_failed,
            postponement_after(target.postponed_count, to_day, from_day),
            target.project.title,
        )
        if target is not None
        else None
    )
    if target is not None:
        db.session.delete(target)
        db.session.flush()

    # "Done" describes a day's session, so it travels within a day and is
    # dropped when the booking lands on another date. "Failed" is the same kind
    # of thing and goes the same way.
    source.slot_date = to_day
    source.slot = to_slot
    source.postponed_count = postponement_after(source.postponed_count, from_day, to_day)
    if to_day != from_day:
        source.is_done = False
        source.is_failed = False
    db.session.flush()

    if displaced is not None:
        project_id, was_done, was_failed, was_postponed, displaced_title = displaced
        db.session.add(
            ProjectDaySlot(
                user_id=user_id,
                project_id=project_id,
                slot_date=from_day,
                slot=from_slot,
                is_done=was_done if to_day == from_day else False,
                is_failed=was_failed if to_day == from_day else False,
                postponed_count=was_postponed,
            )
        )
        return True, f"Swapped with {displaced_title}."

    return True, f"Moved to {to_day.strftime('%d %b')}, slot {to_slot}."


def move_deadline_warning(user_id, from_day, from_slot, to_day, to_slot):
    """What a finished move should be warned about: a session now past its deadline.

    Read off the two blocks once the move has been made, so a swap is weighed on
    both of its sessions. A move inside one sheet is not a move in time and
    cannot make anything later than it was.
    """
    if from_day == to_day:
        return ""
    warnings = []
    for day, slot in ((to_day, to_slot), (from_day, from_slot)):
        booking = ProjectDaySlot.query.filter_by(user_id=user_id, slot_date=day, slot=slot).first()
        if booking is not None and not booking.is_done and not booking.is_failed:
            warning = deadline_warning(booking.project, day)
            if warning:
                warnings.append(warning)
    return " ".join(warnings)


def shift_bookings_forward(user_id, from_day, days=1):
    """
    Take a day off: push the bookings from ``from_day`` on ``days`` days later.

    The chosen day is freed and everything planned for it - and for every day
    after it - simply happens a day later, so the order of the plan survives a
    day that does not. Returns ``(ok, message, moved, late)``; the caller
    commits. ``late`` names the projects whose session the day off has just
    pushed past their session deadline - it goes ahead anyway, and the caller
    warns about them.

    A session already marked done stays exactly where it is. It happened: moving
    it would file work already done under a day it was not done on, and would
    quietly undo it, since "done" belongs to a date and does not travel. So
    taking today off after finishing block A moves what is left of the day and
    leaves A on today - which is also why the day is not always empty afterwards.

    The rows are moved newest first. Every booking lands on the date the one
    after it has just left, so going the other way round would collide with the
    unique constraint on (user, date, slot) halfway through; the flush per row
    keeps the same collision from happening inside one statement batch. A block
    held back by a finished session in the way is held back for the same reason -
    there is nowhere for it to land - and holds back the one behind it in turn.

    A day off is a postponement like any other, so every session it moves counts
    one, and the blocks tint on the schedule accordingly. A session held back
    counts nothing: it did not move.
    """
    if days < 1:
        return False, "A day off is at least one day.", 0, []
    if from_day < today_local():
        return False, "That day is in the past.", 0, []

    entries = (
        ProjectDaySlot.query.filter(
            ProjectDaySlot.user_id == user_id, ProjectDaySlot.slot_date >= from_day
        )
        .order_by(ProjectDaySlot.slot_date.desc())
        .all()
    )
    if not entries:
        return True, f"{from_day.strftime('%d %b')} was already free.", 0, []

    moved = 0
    # Projects a moved session has pushed past their deadline - the day off
    # still goes ahead, as any late booking does.
    late = []
    # The (date, slot) spots nothing may move onto: a finished session, or a
    # booking stuck behind one.
    staying = set()
    for entry in entries:
        target = (entry.slot_date + timedelta(days=days), entry.slot)
        # A failed session ended too, on the day it was meant for - it stays
        # put the way a done one does.
        if entry.is_done or entry.is_failed or target in staying:
            staying.add((entry.slot_date, entry.slot))
            continue

        entry.postponed_count = postponement_after(
            entry.postponed_count, entry.slot_date, target[0]
        )
        was_late = is_after_deadline(entry.project, entry.slot_date)
        entry.slot_date = target[0]
        db.session.flush()
        moved += 1
        if not was_late and is_after_deadline(entry.project, entry.slot_date):
            late.append(entry.project.title)

    return True, _day_off_message(from_day, moved, len(staying)), moved, sorted(set(late))


def _day_off_message(from_day, moved, stayed):
    """What the day off did, in one line: what moved, and what would not.

    "Stayed" is finished sessions and, in principle, whatever was left with
    nowhere to land behind one, so it is counted rather than named.
    """
    day_label = from_day.strftime("%d %b")
    if not moved:
        return f"Nothing moved — a finished session stays on the day it happened."

    blocks = "block" if moved == 1 else "blocks"
    message = f"Day off on {day_label} — {moved} {blocks} moved a day later."
    if stayed:
        message += f" {stayed} stayed put: a finished session does not move."
    return message


def clear_slot(user_id, day, slot):
    """Free a slot. Returns ``(ok, message)``; the caller commits."""
    if slot not in SLOTS:
        return False, "Unknown slot."

    booking = ProjectDaySlot.query.filter_by(user_id=user_id, slot_date=day, slot=slot).first()
    if booking is None:
        return True, "That slot is already free."

    db.session.delete(booking)
    return True, f"Slot {slot} cleared."
