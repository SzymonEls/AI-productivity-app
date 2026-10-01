"""
Tasks: things to do, each on a day or on none.

One list, three places to see it. The Tasks page holds every task, sorted by
the day it is on; the schedule shows each day's tasks on that day's sheet; the
home page shows today's, plus whatever was left behind on a day already gone.
All three are the same rows driven by one script (tasks.js), so a task ticked
off, renamed or moved to the weekend on one of them is the same request on
every one.

A repeating task is one row, not a series. Ticking it off keeps that row as the
record of the occurrence and writes the next one, on the next date its rule
gives; nothing further ahead exists until that one is ticked off in turn, so the
schedule never fills up with copies. Taking the tick back takes the written
occurrence back with it, as long as it has not been done itself.

Moving a task is the common edit, far more than rewriting it - "not today" is
what most tasks hear at least once - so the update endpoint takes a new date as
readily as a new title, and the quick choices in the row's menu (tomorrow, the
weekend, next week) are worked out on the page from the day the server says
it is. See point 21 in ARCHITECTURE.md.
"""

import calendar
from datetime import timedelta

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import TASK_TITLE_MAX_LENGTH, Task
from ..projects.slots import parse_slot_date, today_local
from ..time_tracking.service import utc_now


tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")

# The Completed section of the Tasks page is a record, not a backlog: past this
# many it stops being something anybody scrolls through.
MAX_DONE_LISTED = 200


# The ways a task can come back, in the order the menu offers them. The labels
# are mirrored in tasks.js (REPEAT_LABELS) - change both together.
REPEAT_RULES = {
    "daily": "Every day",
    "weekdays": "Every weekday",
    "weekly": "Every week",
    "biweekly": "Every 2 weeks",
    "monthly": "Every month",
    "yearly": "Every year",
}


def _add_months(day, months):
    """The same day ``months`` later, or the month's last day when it is shorter.

    A task on the 31st repeats on the 30th in a 30-day month, and on the 28th
    or 29th in February.
    """
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def _step(rule, day):
    """The occurrence after ``day`` under ``rule``."""
    if rule == "daily":
        return day + timedelta(days=1)
    if rule == "weekdays":
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        return day
    if rule == "weekly":
        return day + timedelta(days=7)
    if rule == "biweekly":
        return day + timedelta(days=14)
    if rule == "monthly":
        return _add_months(day, 1)
    if rule == "yearly":
        return _add_months(day, 12)
    raise ValueError(rule)


def next_due(rule, due_date, today):
    """When a repeating task is next due, once the occurrence on ``due_date`` is done.

    Counted from the occurrence's own date, so a weekly Monday task stays on
    Mondays however late in the week it is ticked off - but always onto a day
    after today. A daily task left for a week and ticked off now comes back
    tomorrow, not seven times in a row as overdue copies of itself. A task done
    ahead of its day moves on from that day, not from today.
    """
    start = due_date or today
    # Months are counted from the occurrence each time rather than from the step
    # before, so a task on the 31st skipped past a 30-day month lands on the
    # 31st again instead of staying on the 30th.
    months = {"monthly": 1, "yearly": 12}.get(rule)
    if months:
        count = 1
        day = _add_months(start, months)
        while day <= today:
            count += 1
            day = _add_months(start, months * count)
        return day

    day = _step(rule, start)
    while day <= today:
        day = _step(rule, day)
    return day


def _get_user_task_or_404(task_id):
    """Ensure users can only reach their own tasks."""

    return Task.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()


def _payload():
    """Read the body whether it arrives as JSON or as a form, like the inbox does."""
    return request.get_json(silent=True) or request.form


def _clean_title(raw):
    """The title to store, or ``(None, why not)``."""
    title = (raw or "").strip()
    if not title:
        return None, "Write something first."
    if len(title) > TASK_TITLE_MAX_LENGTH:
        return None, f"A task is at most {TASK_TITLE_MAX_LENGTH} characters."
    return title, ""


def _form_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "on", "yes"}


def serialize_task(task):
    """One task as tasks.js wants it."""

    return {
        "id": task.id,
        "title": task.title,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "is_done": bool(task.is_done),
        "repeat": task.repeat_rule,
    }


def _day_order():
    # Within a day: what is still to do first, then in the order written.
    return (Task.is_done.asc(), Task.created_at.asc(), Task.id.asc())


def tasks_from(user_id, start_day, end_day):
    """``{date: [Task, ...]}`` across a range of days, in one query.

    The schedule and the archive draw weeks at a time, so they ask once for the
    whole window, the way they already do for bookings and notes.
    """
    entries = (
        Task.query.filter(
            Task.user_id == user_id,
            Task.due_date >= start_day,
            Task.due_date <= end_day,
        )
        .order_by(Task.due_date.asc(), *_day_order())
        .all()
    )

    by_date = {}
    for entry in entries:
        by_date.setdefault(entry.due_date, []).append(entry)
    return by_date


def overdue_tasks(user_id, today):
    """What was left undone on a day already gone, oldest first.

    The home page lists these above today's: a task does not stop needing doing
    because its day went by, and nowhere else on the way through the day would
    show it.
    """
    return (
        Task.query.filter(
            Task.user_id == user_id,
            Task.is_done.is_(False),
            Task.due_date < today,
        )
        .order_by(Task.due_date.asc(), Task.created_at.asc(), Task.id.asc())
        .all()
    )


def shift_tasks_forward(user_id, from_day, days=1):
    """Move the open tasks from ``from_day`` on ``days`` days later, and count them.

    The third half of a day off, beside the bookings and the notes. A finished
    task stays on the day it was done, for the reason a finished session does:
    the day it sits on is when it happened. The caller commits.
    """
    if days < 1:
        return 0

    entries = Task.query.filter(
        Task.user_id == user_id,
        Task.is_done.is_(False),
        Task.due_date >= from_day,
    ).all()
    for entry in entries:
        entry.due_date = entry.due_date + timedelta(days=days)
    return len(entries)


@tasks_bp.route("")
@login_required
def tasks_page():
    """Every task, by the day it is on: overdue, today, the days ahead, no day, done.

    The page arrives with its tasks as JSON and tasks.js draws the groups: a
    task moved to Friday has to land under Friday without a reload, and the one
    place that knows how the groups are cut is then the script.
    """
    open_tasks = (
        Task.query.filter_by(user_id=current_user.id, is_done=False)
        # No date last: "some day" is after every day that has a name.
        .order_by(Task.due_date.is_(None), Task.due_date.asc(), Task.created_at.asc(), Task.id.asc())
        .all()
    )
    done_tasks = (
        Task.query.filter_by(user_id=current_user.id, is_done=True)
        .order_by(Task.done_at.desc(), Task.id.desc())
        .limit(MAX_DONE_LISTED)
        .all()
    )

    return render_template(
        "tasks/index.html",
        today=today_local(),
        tasks=[serialize_task(task) for task in open_tasks + done_tasks],
        repeat_rules=REPEAT_RULES,
    )


@tasks_bp.route("", methods=["POST"])
@login_required
def add_task():
    """Write one task, on a day or on none. Any day may be given, past included."""

    payload = _payload()
    title, message = _clean_title(payload.get("title"))
    if title is None:
        return jsonify({"ok": False, "message": message}), 400

    raw_date = payload.get("due_date")
    due_date = parse_slot_date(raw_date) if raw_date else None
    if raw_date and due_date is None:
        return jsonify({"ok": False, "message": "That is not a date."}), 400

    rule = (payload.get("repeat") or "").strip() or None
    if rule is not None and rule not in REPEAT_RULES:
        return jsonify({"ok": False, "message": "Unknown repeat."}), 400
    if rule and due_date is None:
        due_date = today_local()

    task = Task(user_id=current_user.id, title=title, due_date=due_date, repeat_rule=rule)
    db.session.add(task)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the task."}), 500

    return jsonify({"ok": True, "message": "Task added.", "task": serialize_task(task)})


@tasks_bp.route("/<int:task_id>/update", methods=["POST"])
@login_required
def update_task(task_id):
    """Change any of a task's title, day and state - only the keys that are sent.

    ``due_date`` sent empty takes the task off every day, which is the menu's
    "No date"; left out, the day stays as it was. An emptied title is refused
    rather than read as a delete, the way an emptied day note is: clearing the
    text by accident is not the same gesture as reaching for Delete.
    """
    task = _get_user_task_or_404(task_id)
    payload = _payload()
    message = "Task saved."

    if "title" in payload:
        title, why_not = _clean_title(payload.get("title"))
        if title is None:
            return jsonify({"ok": False, "message": why_not}), 400
        task.title = title

    if "due_date" in payload:
        raw_date = payload.get("due_date")
        due_date = parse_slot_date(raw_date) if raw_date else None
        if raw_date and due_date is None:
            return jsonify({"ok": False, "message": "That is not a date."}), 400
        task.due_date = due_date
        message = (
            f"Moved to {due_date.strftime('%a %d %b')}." if due_date else "Date removed."
        )

    if "repeat" in payload:
        rule = (payload.get("repeat") or "").strip() or None
        if rule is not None and rule not in REPEAT_RULES:
            return jsonify({"ok": False, "message": "Unknown repeat."}), 400
        task.repeat_rule = rule
        message = f"Repeats: {REPEAT_RULES[rule].lower()}." if rule else "No longer repeats."
        # A repetition is counted from a day, so a repeating task has one - today,
        # when it had none.
        if rule and task.due_date is None:
            task.due_date = today_local()

    next_task = None
    removed_id = None
    if "is_done" in payload:
        is_done = _form_bool(payload.get("is_done"))
        if is_done != task.is_done:
            task.is_done = is_done
            task.done_at = utc_now() if is_done else None
            if is_done and task.repeat_rule:
                next_task = _write_next_occurrence(task)
            elif not is_done:
                removed_id = _take_back_next_occurrence(task)
        message = "Done." if is_done else "Reopened."
        if next_task is not None:
            message = f"Done. Next: {next_task.due_date.strftime('%a %d %b')}."

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the task."}), 500

    return jsonify(
        {
            "ok": True,
            "message": message,
            "task": serialize_task(task),
            # The occurrence a tick just wrote, and the one taking it back just
            # removed, so the page can show or drop it without a reload.
            "next": serialize_task(next_task) if next_task is not None else None,
            "removed_id": removed_id,
        }
    )


def _write_next_occurrence(task):
    """Add the next occurrence of a repeating task that was just ticked off.

    The ticked-off row stays as it is - done, on its own day, still saying what
    rule it followed - and the rule travels on to the new one. Not if this one
    has written an occurrence already: an open one is returned as it is, so
    ticking, unticking and ticking again cannot leave two, and a finished one
    means the series has moved on past it - re-ticking an old record in
    Completed must not start a second series. The caller commits.
    """
    existing = Task.query.filter_by(user_id=task.user_id, previous_task_id=task.id).first()
    if existing is not None:
        return None if existing.is_done else existing

    next_task = Task(
        user_id=task.user_id,
        title=task.title,
        due_date=next_due(task.repeat_rule, task.due_date, today_local()),
        repeat_rule=task.repeat_rule,
        previous_task_id=task.id,
    )
    db.session.add(next_task)
    db.session.flush()
    return next_task


def _take_back_next_occurrence(task):
    """Remove the occurrence a reopened task wrote, and return its id.

    Reopening says the tick was a mistake, so the occurrence it wrote should not
    be there either. One that has been done in the meantime stays: that is a
    record of its own now. The caller commits.
    """
    written = Task.query.filter_by(
        user_id=task.user_id, previous_task_id=task.id, is_done=False
    ).first()
    if written is None:
        return None
    written_id = written.id
    db.session.delete(written)
    return written_id


@tasks_bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    """Remove one task. One that has already gone counts as removed.

    The row is taken off the page before the request goes out, as a day note's
    is, so a second click must not turn into an error the page has to undo.
    """
    task = Task.query.filter_by(id=task_id, user_id=current_user.id).first()
    if task is None:
        return jsonify({"ok": True, "message": "That task is already gone."})

    # The occurrence this one wrote forgets where it came from. SQLite can hand a
    # deleted row's id to the next task added, and a link left pointing at it
    # would make that unrelated task look like this one when it is ticked off.
    Task.query.filter_by(user_id=current_user.id, previous_task_id=task.id).update(
        {Task.previous_task_id: None}
    )
    db.session.delete(task)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to delete the task."}), 500

    return jsonify({"ok": True, "message": "Task deleted."})
