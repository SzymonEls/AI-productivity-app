"""
The tools Claude gets over MCP, and the one rule they all keep: a private
project's contents never leave the server and are never changed through here.

**Private projects.** On the pages ``is_private`` is a curtain the browser
draws; here it is enforced. A private project is listed, planned and timed like
any other - its title, its bookings, its deadline and its settings are the
planning - but everything written *in* it reads back as ``[private]``: the
thoughts (``short_goal``), the plan (``long_goal``) and its archive, the plan's
first heading wherever a block or a timer would quote it, the milestone it waits
for, and the descriptions of its timed sessions. The tools that would write into
those - update_project's thoughts and plan, filing an inbox item into it - refuse
it. Nothing here can switch ``is_private`` either way, and a project made here
is never private. Every reader below goes through ``_hidden``/``_step``, so there
is one place that decides.

**Reads** are serialised here, field by field, rather than passed on from the
pages' JSON: a key added to a page's payload later reaches Claude only when it
is added here too.

**Writes** go through the very endpoint the page calls (``_through``), so a
booking from Claude obeys the two-block rule, a ticked repeating task writes its
next occurrence, and so on, exactly as a click does. Only the keys in
``PASSED_THROUGH`` come back from those answers - never a page's whole payload,
which can carry plan text. The project settings, whose endpoints answer with a
redirect and a flash, are written here directly with the same validation.
"""

import json
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from ..api import routes as api_routes
from ..extensions import db
from ..inbox import routes as inbox_routes
from ..integrations.feeds import events_by_date
from ..models import InboxItem, Project, ProjectDaySlot, Task
from ..projects import routes as project_routes
from ..projects.day_notes import notes_from
from ..projects.groups import group_heading
from ..projects.slots import (
    DEADLINE_RULE_DAY_BEFORE,
    DEADLINE_RULE_SAME_DAY,
    MAX_SESSIONS_PER_WEEK,
    MIN_SESSIONS_PER_WEEK,
    SLOTS,
    is_after_deadline,
    parse_slot_date,
    planned_session_labels_by_project,
    project_bookings,
    project_deadline_label,
    slot_candidates,
    slots_from,
    today_local,
    unscheduled_projects,
)
from ..tasks import routes as task_routes
from ..tasks.routes import REPEAT_RULES, overdue_tasks, serialize_task, tasks_from
from ..time_tracking.service import (
    active_entry_for_user,
    app_timezone,
    ensure_utc,
    entry_elapsed_seconds,
    first_plan_section_title,
    format_duration,
    project_last_session_labels,
)


PRIVATE = "[private]"
PRIVATE_REFUSAL = (
    "This project is private: its thoughts and plan cannot be read or changed over MCP. "
    "Ask the user to do it in the app."
)
PROJECT_TITLE_MAX_LENGTH = 150
# A schedule read covers two months at most - enough to plan with, short enough
# that one call cannot dump the whole history.
MAX_SCHEDULE_DAYS = 62
MAX_DONE_TASKS_LISTED = 50

INSTRUCTIONS = (
    "This server is the user's productivity app: projects, each with thoughts and a "
    "Markdown plan; days of three blocks (A and B for real work, C a spare) each holding "
    "one project's session or one task; tasks; notes against days; an inbox of captured "
    "thoughts; and a timer. A project may have at most one session today plus one on a "
    "later day; the app refuses anything else and says why. Dates are YYYY-MM-DD in the "
    f"app's timezone. Projects marked private show {PRIVATE} in place of their thoughts, "
    "plan, current step and session notes; that is deliberate, so never guess at those or "
    "try to work around it. You can still plan private projects' sessions. The user makes "
    "the decisions: propose changes to the plan before making many of them."
)


class ToolError(Exception):
    """A refusal to send back to Claude as the tool's answer."""


_TOOLS = {}


def tool(name, description, properties=None, required=(), read_only=False, destructive=False):
    def register(handler):
        _TOOLS[name] = {
            "definition": {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": properties or {},
                    "required": list(required),
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": read_only,
                    "destructiveHint": destructive,
                    "openWorldHint": False,
                },
            },
            "handler": handler,
        }
        return handler

    return register


def definitions():
    return [entry["definition"] for entry in _TOOLS.values()]


def exists(name):
    return name in _TOOLS


def call(user, name, arguments):
    """Run one tool and wrap its answer the way tools/call returns one."""
    try:
        data = _TOOLS[name]["handler"](user, arguments)
    except ToolError as refusal:
        db.session.rollback()
        data = {"ok": False, "message": str(refusal)}
    except Exception:
        db.session.rollback()
        raise
    data = {"ok": True, **data}
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}],
        "isError": not data["ok"],
    }


# --- privacy -----------------------------------------------------------------------------


def is_private(project):
    return bool(project is not None and project.is_private)


def _hidden(project, text):
    """Text written inside ``project``, or the placeholder when it is private."""
    return PRIVATE if is_private(project) else (text or "")


def _step(project):
    """What a session of the project is about, as its block names it.

    A plan's first heading for a project; a group's members for a group, whose
    own plan is rarely where the work is (and whose member titles are titles).
    """
    if project is None:
        return ""
    if project.is_group:
        return group_heading(project)
    return _hidden(project, first_plan_section_title(project.long_goal))


# --- reading -----------------------------------------------------------------------------


def _brief(project):
    return {"id": project.id, "title": project.title, "is_private": bool(project.is_private)}


def _deadline(project):
    if project.session_deadline is None:
        return None
    return {
        "date": project.session_deadline.isoformat(),
        "time": project.session_deadline_time.strftime("%H:%M") if project.session_deadline_time else None,
        "session_rule": DEADLINE_RULE_DAY_BEFORE if project.session_deadline_day_before else DEADLINE_RULE_SAME_DAY,
        "label": project_deadline_label(project),
    }


def _project_summary(project, booked_labels, last_labels):
    data = {
        **_brief(project),
        "is_group": bool(project.is_group),
        "is_archived": bool(project.is_archived),
        "is_starred": bool(project.is_starred),
        "is_problematic": bool(project.is_problematic),
        "sessions_per_week": project.sessions_per_week,
        "deadline": _deadline(project),
        "current_step": _step(project),
        "booked": booked_labels.get(project.id, []),
        "last_session": last_labels.get(project.id, ""),
    }
    if project.group is not None:
        data["group"] = _brief(project.group)
    if project.waiting_for is not None:
        target = project.waiting_for
        data["waiting_for"] = {
            "project": _brief(target),
            # The milestone is a line of the other project's plan.
            "milestone": PRIVATE
            if is_private(project) or is_private(target)
            else (project.waiting_for_note or ""),
        }
    return data


def _booking(booking):
    return {
        "project": _brief(booking.project),
        "step": _step(booking.project),
        "is_done": bool(booking.is_done),
        "is_failed": bool(booking.is_failed),
    }


def _event(entry):
    return {
        "summary": entry["summary"],
        "time": entry.get("time_label") or ("all day" if entry.get("all_day") else ""),
        "calendar": entry["calendar"],
    }


def _schedule(user, first, last):
    booked = slots_from(user.id, first, last)
    tasks = tasks_from(user.id, first, last)
    notes = notes_from(user.id, first, last)
    events = events_by_date(user.id, first, last)

    days = []
    day = first
    while day <= last:
        day_tasks = tasks.get(day, [])
        in_block = {task.slot: task for task in day_tasks if task.slot}
        blocks = []
        for letter in SLOTS:
            booking = booked.get(day, {}).get(letter)
            task = in_block.get(letter)
            blocks.append(
                {
                    "slot": letter,
                    "session": _booking(booking) if booking else None,
                    "task": serialize_task(task) if task else None,
                }
            )
        days.append(
            {
                "date": day.isoformat(),
                "weekday": day.strftime("%A"),
                "blocks": blocks,
                "tasks": [serialize_task(task) for task in day_tasks if not task.slot],
                "notes": [{"id": note.id, "text": note.body} for note in notes.get(day, [])],
                # A grouped calendar's one summary line is dropped for the
                # events it folds, which say more.
                "events": [_event(entry) for entry in events.get(day, []) if entry["group_role"] != "line"],
            }
        )
        day += timedelta(days=1)
    return days


def _timer(entry):
    if entry is None:
        return None
    project = entry.project
    elapsed = entry_elapsed_seconds(entry)
    return {
        "project": _brief(project) if project else {"id": None, "title": entry.display_project_title},
        "started_at": ensure_utc(entry.started_at).isoformat(),
        "elapsed": format_duration(elapsed),
        "elapsed_seconds": elapsed,
        "note": _hidden(project, entry.description),
    }


def _user_project(user, project_id):
    project = Project.query.filter_by(id=_int(project_id, "project_id"), user_id=user.id).first()
    if project is None:
        raise ToolError("Unknown project.")
    return project


def _int(value, name):
    if isinstance(value, bool):
        raise ToolError(f"{name} must be a number.")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be a number.") from None


def _day(arguments, name, default=None):
    raw = arguments.get(name)
    if raw in (None, ""):
        if default is not None:
            return default
        raise ToolError(f"Give {name} as YYYY-MM-DD.")
    day = parse_slot_date(raw)
    if day is None:
        raise ToolError(f"{name} must be a date as YYYY-MM-DD.")
    return day


def _slot(arguments, name="slot"):
    letter = str(arguments.get(name) or "").strip().upper()
    if letter not in SLOTS:
        raise ToolError(f"{name} must be A, B or C.")
    return letter


DATE = {"type": "string", "description": "A day as YYYY-MM-DD."}
SLOT = {"type": "string", "enum": list(SLOTS), "description": "The block: A, B or C."}
PROJECT_ID = {"type": "integer", "description": "A project's id, from list_projects."}


@tool(
    "get_today",
    "Today at a glance: the three blocks (A, B, C) with the session or task in each, today's "
    "other tasks and the ones left overdue, notes, calendar events, the running timer, how "
    "many thoughts wait in the inbox, and the projects with no next session planned.",
    read_only=True,
)
def get_today(user, arguments):
    today = today_local()
    return {
        "date": today.isoformat(),
        "timezone": str(app_timezone()),
        "today": _schedule(user, today, today)[0],
        "overdue_tasks": [serialize_task(task) for task in overdue_tasks(user.id, today)],
        "timer": _timer(active_entry_for_user(user.id)),
        "inbox_count": InboxItem.query.filter_by(user_id=user.id).count(),
        "not_planned": [_brief(project) for project in unscheduled_projects(user.id)],
    }


@tool(
    "list_projects",
    "Every project with its settings and where it stands: sessions a week it should get, "
    "deadline, current step (the plan's first heading), what is booked, the last session, "
    f"whether it waits for another project. Private ones show {PRIVATE} for their step.",
    {"include_archived": {"type": "boolean", "description": "Include archived projects too."}},
    read_only=True,
)
def list_projects(user, arguments):
    query = Project.query.filter_by(user_id=user.id)
    if not arguments.get("include_archived"):
        query = query.filter_by(is_archived=False)
    projects = query.order_by(func.lower(Project.title).asc()).all()
    booked = planned_session_labels_by_project(user.id)
    last = project_last_session_labels(user.id, projects)
    return {"projects": [_project_summary(project, booked, last) for project in projects]}


@tool(
    "get_project",
    "One project in full: its settings, its thoughts, its Markdown plan and the archived part "
    f"of the plan, and a group's member projects. A private project returns {PRIVATE} in place "
    "of the thoughts and the plan.",
    {"project_id": PROJECT_ID},
    required=("project_id",),
    read_only=True,
)
def get_project(user, arguments):
    project = _user_project(user, arguments.get("project_id"))
    booked = planned_session_labels_by_project(user.id)
    last = project_last_session_labels(user.id, [project])
    data = {
        **_project_summary(project, booked, last),
        "thoughts": _hidden(project, project.short_goal),
        "plan": _hidden(project, project.long_goal),
        "archived_plan": _hidden(project, project.archived_long_goal),
    }
    if project.is_group:
        data["members"] = [_brief(member) for member in project.active_members]
    if is_private(project):
        data["private_notice"] = PRIVATE_REFUSAL
    return {"project": data}


@tool(
    "get_schedule",
    "The days from start_date to end_date (at most 62): each day's blocks with their session "
    "or task, its other tasks, its notes and its calendar events. Defaults to the next two "
    "weeks from today. Past days are the archive.",
    {"start_date": DATE, "end_date": DATE},
    read_only=True,
)
def get_schedule(user, arguments):
    first = _day(arguments, "start_date", default=today_local())
    last = _day(arguments, "end_date", default=first + timedelta(days=13))
    if last < first:
        raise ToolError("end_date is before start_date.")
    if (last - first).days >= MAX_SCHEDULE_DAYS:
        raise ToolError(f"Ask for at most {MAX_SCHEDULE_DAYS} days at a time.")
    return {"days": _schedule(user, first, last)}


@tool(
    "list_tasks",
    "Open tasks, by day (tasks with no day last), optionally with the most recently done ones.",
    {"include_done": {"type": "boolean", "description": f"Also list the last {MAX_DONE_TASKS_LISTED} done."}},
    read_only=True,
)
def list_tasks(user, arguments):
    open_tasks = (
        Task.query.filter_by(user_id=user.id, is_done=False)
        .order_by(Task.due_date.is_(None), Task.due_date.asc(), Task.created_at.asc(), Task.id.asc())
        .all()
    )
    data = {"open": [serialize_task(task) for task in open_tasks]}
    if arguments.get("include_done"):
        done = (
            Task.query.filter_by(user_id=user.id, is_done=True)
            .order_by(Task.done_at.desc(), Task.id.desc())
            .limit(MAX_DONE_TASKS_LISTED)
            .all()
        )
        data["done"] = [serialize_task(task) for task in done]
    return data


@tool("list_inbox", "The thoughts waiting in the inbox to be filed into a project, newest first.", read_only=True)
def list_inbox(user, arguments):
    return {"items": [{"id": item.id, "text": item.body} for item in inbox_routes.items_for(user.id)]}


@tool(
    "block_options",
    "Which projects could take one block on one day, and why the others cannot (the "
    "two-block rule, a taken block) - what the planner offers when booking.",
    {"date": DATE, "slot": SLOT},
    required=("date", "slot"),
    read_only=True,
)
def block_options(user, arguments):
    day, letter = _day(arguments, "date"), _slot(arguments)
    candidates = slot_candidates(user.id, day, letter)
    projects = {
        project.id: project
        for project in Project.query.filter(
            Project.user_id == user.id, Project.id.in_([entry["id"] for entry in candidates])
        ).all()
    }
    return {
        "options": [
            {
                **_brief(projects[entry["id"]]),
                "step": _step(projects[entry["id"]]),
                "can_take": entry["can_take"],
                "reason": entry["reason"],
                "deadline_warning": entry["deadline_warning"],
                "last_session": entry["last_session"],
            }
            for entry in candidates
        ]
    }


# --- writing through the pages' own endpoints ---------------------------------------------


# What may come back from a page's JSON answer. Everything else is dropped.
PASSED_THROUGH = (
    "message",
    "warning",
    "needs_next_session",
    "is_done",
    "is_failed",
    "is_problematic",
    "task",
    "next",
    "removed_id",
    "note",
    "item",
)


def _through(view, payload, **view_args):
    """Call one of the pages' JSON endpoints as the MCP user and keep its verdict.

    The request is a nested one on the same app context, so ``current_user``
    (set by routes._serve) is the token's owner, and the endpoint validates,
    commits and words its answer exactly as it does for the page.
    """
    with current_app.test_request_context(method="POST", json=payload):
        try:
            response = current_app.make_response(view(**view_args))
        except HTTPException as error:
            return {"ok": False, "message": "Not found." if error.code == 404 else (error.description or "Refused.")}
        body = response.get_json(silent=True) or {}
    data = {"ok": bool(body.get("ok")) and response.status_code < 400}
    data.update({key: body[key] for key in PASSED_THROUGH if body.get(key) not in (None, "")})
    if not data["ok"] and "message" not in data:
        data["message"] = "The app refused that."
    return data


def _next_session_warning(user, project):
    """The reminder the page asks as a question when today's session ends."""
    _, upcoming = project_bookings(user.id, project.id)
    if upcoming is None:
        return f"Nothing is booked for {project.title} after today - plan its next session."
    return ""


@tool(
    "book_session",
    "Book a project's session into a block on a day (today or later). Refused with the "
    "reason when the block is taken or the two-block rule says no; a warning comes back "
    "when the day is past the project's deadline.",
    {"project_id": PROJECT_ID, "date": DATE, "slot": SLOT},
    required=("project_id", "date", "slot"),
)
def book_session(user, arguments):
    project = _user_project(user, arguments.get("project_id"))
    return _through(
        project_routes.assign_project_slot,
        {"project_id": project.id, "date": _day(arguments, "date").isoformat(), "slot": _slot(arguments)},
    )


@tool(
    "move_session",
    "Move the session in one block to another block and/or day, swapping with a session "
    "already there - what dragging a block on the schedule does.",
    {"from_date": DATE, "from_slot": SLOT, "to_date": DATE, "to_slot": SLOT},
    required=("from_date", "from_slot", "to_date", "to_slot"),
)
def move_session(user, arguments):
    return _through(
        project_routes.move_project_slot,
        {
            "from_date": _day(arguments, "from_date").isoformat(),
            "from_slot": _slot(arguments, "from_slot"),
            "to_date": _day(arguments, "to_date").isoformat(),
            "to_slot": _slot(arguments, "to_slot"),
        },
    )


@tool(
    "clear_block",
    "Remove the session booked in one block, leaving the block free.",
    {"date": DATE, "slot": SLOT},
    required=("date", "slot"),
    destructive=True,
)
def clear_block(user, arguments):
    return _through(
        project_routes.clear_project_slot,
        {"date": _day(arguments, "date").isoformat(), "slot": _slot(arguments)},
    )


@tool(
    "set_session_state",
    "Mark the session in one block done, failed, or open again. Done works on today and on "
    "past days; failed (which flags the project problematic) only on today's session.",
    {"date": DATE, "slot": SLOT, "state": {"type": "string", "enum": ["done", "failed", "open"]}},
    required=("date", "slot", "state"),
)
def set_session_state(user, arguments):
    day, letter = _day(arguments, "date"), _slot(arguments)
    state = arguments.get("state")
    today = today_local()
    booking = ProjectDaySlot.query.filter_by(user_id=user.id, slot_date=day, slot=letter).first()
    if booking is None:
        raise ToolError(f"Block {letter} on {day.isoformat()} holds no session.")
    project = booking.project
    block = {"date": day.isoformat(), "slot": letter}

    if state == "done":
        if day > today:
            raise ToolError("A session still to come cannot be done yet.")
        result = _through(project_routes.toggle_block_session_done, {**block, "done": "1"})
    elif state == "failed":
        if day != today:
            raise ToolError("Only today's session can be marked failed.")
        result = _through(
            project_routes.toggle_session_failed,
            {"failed": "1", "skip_next": "1"},
            project_id=project.id,
        )
    elif state == "open":
        if booking.is_failed:
            if day != today:
                raise ToolError("Only today's failed session can be reopened.")
            result = _through(project_routes.toggle_session_failed, {"failed": "0"}, project_id=project.id)
        else:
            result = _through(project_routes.toggle_block_session_done, {**block, "done": "0"})
    else:
        raise ToolError("state must be done, failed or open.")

    if result["ok"] and state in ("done", "failed") and day == today:
        warning = _next_session_warning(user, project)
        if warning:
            result["warning"] = warning
    return result


@tool(
    "take_day_off",
    "Free a day by moving every open session, note and task from that day on one day later. "
    "Finished sessions and tasks stay where they were done.",
    {"date": DATE},
    required=("date",),
)
def take_day_off(user, arguments):
    return _through(project_routes.schedule_day_off, {"date": _day(arguments, "date").isoformat()})


TASK_PROPERTIES = {
    "title": {"type": "string"},
    "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD, or null for no day."},
    "repeat": {
        "type": ["string", "null"],
        "description": "One of " + ", ".join(REPEAT_RULES) + ", or weeks:N (3-52), or null for none.",
    },
}


@tool(
    "add_task",
    "Add a task, on a day or on none, optionally repeating.",
    TASK_PROPERTIES,
    required=("title",),
)
def add_task(user, arguments):
    return _through(task_routes.add_task, _sent(arguments, ("title", "due_date", "repeat")))


@tool(
    "update_task",
    "Change a task: only the fields given change. due_date null takes it off every day; slot "
    "puts it in one of its day's blocks in place of a session (null takes it out); is_done "
    "ticks it off (a repeating task then gets its next occurrence) or reopens it.",
    {
        "task_id": {"type": "integer"},
        **TASK_PROPERTIES,
        "slot": {"type": ["string", "null"], "enum": [*SLOTS, None]},
        "is_done": {"type": "boolean"},
    },
    required=("task_id",),
)
def update_task(user, arguments):
    payload = _sent(arguments, ("title", "due_date", "repeat", "slot", "is_done"))
    if payload.get("slot") is None and "slot" in payload:
        payload["slot"] = ""
    return _through(task_routes.update_task, payload, task_id=_int(arguments.get("task_id"), "task_id"))


@tool("delete_task", "Delete a task.", {"task_id": {"type": "integer"}}, required=("task_id",), destructive=True)
def delete_task(user, arguments):
    return _through(task_routes.delete_task, {}, task_id=_int(arguments.get("task_id"), "task_id"))


@tool(
    "add_day_note",
    "Write a note against a day (any day, past included).",
    {"date": DATE, "text": {"type": "string"}},
    required=("date", "text"),
)
def add_day_note(user, arguments):
    return _through(
        project_routes.add_day_note,
        {"date": _day(arguments, "date").isoformat(), "body": arguments.get("text")},
    )


@tool(
    "update_day_note",
    "Rewrite a day note, by its id from get_schedule.",
    {"note_id": {"type": "integer"}, "text": {"type": "string"}},
    required=("note_id", "text"),
)
def update_day_note(user, arguments):
    return _through(
        project_routes.update_day_note,
        {"note_id": _int(arguments.get("note_id"), "note_id"), "body": arguments.get("text")},
    )


@tool("delete_day_note", "Delete a day note.", {"note_id": {"type": "integer"}}, required=("note_id",), destructive=True)
def delete_day_note(user, arguments):
    return _through(project_routes.delete_day_note, {"note_id": _int(arguments.get("note_id"), "note_id")})


@tool("add_to_inbox", "Capture a thought in the inbox.", {"text": {"type": "string"}}, required=("text",))
def add_to_inbox(user, arguments):
    return _through(inbox_routes.add_item, {"body": arguments.get("text")})


@tool(
    "file_inbox_item",
    "File an inbox thought into a project's plan as a to-do, and take it out of the inbox. "
    "Not into a private project.",
    {"item_id": {"type": "integer"}, "project_id": PROJECT_ID},
    required=("item_id", "project_id"),
)
def file_inbox_item(user, arguments):
    project = _user_project(user, arguments.get("project_id"))
    if is_private(project):
        raise ToolError(PRIVATE_REFUSAL)
    return _through(
        inbox_routes.file_item,
        {"project_id": project.id},
        item_id=_int(arguments.get("item_id"), "item_id"),
    )


@tool(
    "delete_inbox_item",
    "Throw an inbox thought away without filing it.",
    {"item_id": {"type": "integer"}},
    required=("item_id",),
    destructive=True,
)
def delete_inbox_item(user, arguments):
    return _through(inbox_routes.delete_item, {}, item_id=_int(arguments.get("item_id"), "item_id"))


@tool(
    "start_timer",
    "Start timing a project's session now; a timer running for another project is stopped first.",
    {"project_id": PROJECT_ID},
    required=("project_id",),
)
def start_timer(user, arguments):
    project = _user_project(user, arguments.get("project_id"))
    # The API's views sit behind its own token check, which reads a header this
    # nested request does not carry; the user it would set is set already.
    result = _through(api_routes.start_timer.__wrapped__, {"project_id": project.id})
    if result["ok"]:
        result["timer"] = _timer(active_entry_for_user(user.id))
    return result


@tool(
    "stop_timer",
    "Stop the running timer, optionally saying what the session got done.",
    {"note": {"type": "string", "description": "What was done, kept with the session."}},
)
def stop_timer(user, arguments):
    result = _through(api_routes.stop_timer.__wrapped__, {"description": arguments.get("note") or ""})
    if result["ok"]:
        result["message"] = "Timer stopped."
    return result


def _sent(arguments, names):
    """The arguments Claude actually gave, so that a field left out stays as it is."""
    return {name: arguments[name] for name in names if name in arguments}


# --- project settings, written here --------------------------------------------------------


def _sessions_per_week(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not MIN_SESSIONS_PER_WEEK < number <= MAX_SESSIONS_PER_WEEK:
        raise ToolError(
            f"sessions_per_week has to be more than {MIN_SESSIONS_PER_WEEK} and at most "
            f"{MAX_SESSIONS_PER_WEEK} - 0.25 is one every four weeks."
        )
    return number


def _title(value):
    title = (value or "").strip() if isinstance(value, str) else ""
    if not title:
        raise ToolError("A project needs a name.")
    if len(title) > PROJECT_TITLE_MAX_LENGTH:
        raise ToolError(f"A project's name is at most {PROJECT_TITLE_MAX_LENGTH} characters.")
    return title


def _commit(failure):
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise ToolError(failure) from None


TEXT = {"type": "string"}


@tool(
    "create_project",
    "Create a project (never a private one - the user marks that in the app). Only the "
    "title is required.",
    {
        "title": TEXT,
        "thoughts": {"type": "string", "description": "Free-form thoughts about the project."},
        "plan": {"type": "string", "description": "The Markdown plan; '# ' headings are its steps."},
        "sessions_per_week": {"type": "number", "description": "Fewest sessions a week, above 0 up to 7."},
    },
    required=("title",),
)
def create_project(user, arguments):
    project = Project(
        owner=user,
        title=_title(arguments.get("title")),
        short_goal=(arguments.get("thoughts") or "").strip(),
        long_goal=(arguments.get("plan") or "").strip(),
        is_private=False,
        sessions_per_week=_sessions_per_week(arguments["sessions_per_week"])
        if "sessions_per_week" in arguments
        else 1.0,
    )
    db.session.add(project)
    _commit("Failed to create the project.")
    return {"message": "Project created.", "project": _brief(project)}


@tool(
    "update_project",
    "Change a project: only the fields given change. thoughts and plan replace the whole text, "
    "so read the project first. A private project's thoughts and plan cannot be changed; its "
    "other settings can.",
    {
        "project_id": PROJECT_ID,
        "title": TEXT,
        "thoughts": TEXT,
        "plan": TEXT,
        "sessions_per_week": {"type": "number"},
        "is_starred": {"type": "boolean"},
        "is_problematic": {"type": "boolean"},
        "is_archived": {"type": "boolean", "description": "Archived projects drop out of the planning."},
    },
    required=("project_id",),
)
def update_project(user, arguments):
    project = _user_project(user, arguments.get("project_id"))
    if is_private(project) and ("thoughts" in arguments or "plan" in arguments):
        raise ToolError(PRIVATE_REFUSAL)

    if "title" in arguments:
        project.title = _title(arguments["title"])
    if "thoughts" in arguments:
        project.short_goal = (arguments["thoughts"] or "").strip()
    if "plan" in arguments:
        project.long_goal = (arguments["plan"] or "").strip()
    if "sessions_per_week" in arguments:
        project.sessions_per_week = _sessions_per_week(arguments["sessions_per_week"])
    for flag in ("is_starred", "is_problematic", "is_archived"):
        if flag in arguments:
            setattr(project, flag, bool(arguments[flag]))

    _commit("Failed to save the project.")
    return {"message": "Project updated.", "project": _brief(project)}


@tool(
    "set_project_deadline",
    "Set a project's deadline, or clear it with date null. session_rule says whether its next "
    "session may happen on the deadline day (same_day) or must come a day before (day_before).",
    {
        "project_id": PROJECT_ID,
        "date": {"type": ["string", "null"], "description": "YYYY-MM-DD, or null to clear."},
        "time": {"type": ["string", "null"], "description": "Optional hour as HH:MM."},
        "session_rule": {"type": "string", "enum": [DEADLINE_RULE_SAME_DAY, DEADLINE_RULE_DAY_BEFORE]},
    },
    required=("project_id", "date"),
)
def set_project_deadline(user, arguments):
    project = _user_project(user, arguments.get("project_id"))
    if arguments.get("date") in (None, ""):
        project.session_deadline = None
        project.session_deadline_time = None
        project.session_deadline_day_before = False
        _commit("Failed to save the deadline.")
        return {"message": "Deadline removed."}

    deadline = _day(arguments, "date")
    day_before = arguments.get("session_rule") == DEADLINE_RULE_DAY_BEFORE
    raw_time = (arguments.get("time") or "").strip()
    today = today_local()
    if deadline < today:
        raise ToolError("A deadline has to be today or later.")
    if day_before and deadline <= today:
        raise ToolError("With the session a day before, the deadline has to be tomorrow or later.")
    try:
        deadline_time = datetime.strptime(raw_time, "%H:%M").time() if raw_time else None
    except ValueError:
        raise ToolError("time should look like 14:30.") from None

    project.session_deadline = deadline
    project.session_deadline_time = deadline_time
    project.session_deadline_day_before = day_before
    _commit("Failed to save the deadline.")

    result = {"message": f"Deadline set to {project_deadline_label(project)}."}
    late = [
        booking
        for booking in ProjectDaySlot.query.filter(
            ProjectDaySlot.user_id == user.id,
            ProjectDaySlot.project_id == project.id,
            ProjectDaySlot.slot_date >= today,
            ProjectDaySlot.is_done.is_(False),
        ).order_by(ProjectDaySlot.slot_date.asc())
        if is_after_deadline(project, booking.slot_date)
    ]
    if late:
        result["warning"] = (
            f"Already booked for {late[0].slot_date.isoformat()} in block {late[0].slot} - after the deadline."
        )
    return result
