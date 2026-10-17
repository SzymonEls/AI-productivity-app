import re
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..markdown_utils import TAG_PATTERN, render_project_markdown
from ..models import Project, ProjectDaySlot, ProjectTimelineGroup, ProjectTimelineItem
from ..time_tracking.service import (
    daily_totals_by_project,
    first_plan_section_title,
    project_last_session_labels,
    today_project_summary,
    utc_now,
)
from ..integrations.feeds import events_by_date, has_grouped_feeds, has_stale_feeds
from .day_notes import add_note, delete_note, notes_from, shift_notes_forward, update_note
from ..tasks.routes import shift_tasks_forward, tasks_from
from .slots import (
    ARCHIVE_WEEKS,
    DAYS_PER_WEEK,
    MAX_CALENDAR_WEEKS,
    MAX_SCROLL_WEEKS,
    SLOTS,
    TIMED_SLOTS,
    assign_slot,
    booking_note,
    calendar_weeks,
    clear_slot,
    deadline_label,
    deadline_time_label,
    deadline_warning,
    first_booked_day,
    is_after_deadline,
    move_booking,
    move_deadline_warning,
    parse_slot_date,
    past_calendar_weeks,
    planned_session_labels,
    planned_session_labels_by_project,
    project_deadline_label,
    project_statistics,
    schedule_window,
    set_block_done,
    set_session_done,
    set_session_failed,
    shift_bookings_forward,
    slot_candidates,
    slots_for_date,
    today_local,
    unscheduled_projects,
    warn_level,
    warn_title,
    weeks_to_cover,
)


projects_bp = Blueprint("projects", __name__, url_prefix="/projects")


def _get_user_project_or_404(project_id):
    """Ensure users can only access their own projects."""

    return Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()


@projects_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Kept only so existing links keep working.

    This view moved to the home page in 1.5.0. Bookmarks, the redirects spread
    around the code, and above all the start_url baked into already-installed
    PWAs still point here, so the route stays as a redirect rather than a 404.
    """
    return redirect(url_for("main.home"))


def _block_deadline(booking, day):
    """The project's session deadline, as a booked block shows it.

    ``shows_deadline`` is whether the block prints it in place of its letter:
    only on a session still to be done, since a finished one has met it. The
    date itself is passed either way - the board moves a block onto another day
    in place, which reopens it, and then has to know what to print.
    """
    project = booking.project if booking else None
    if project is None or project.session_deadline is None:
        return {
            "deadline": None,
            "deadline_time": "",
            "deadline_label": "",
            "after_deadline": False,
            "shows_deadline": False,
        }
    return {
        "deadline": project.session_deadline,
        # "14:30" when the deadline has an hour; printed under the day.
        "deadline_time": deadline_time_label(project),
        "deadline_label": project_deadline_label(project),
        "after_deadline": is_after_deadline(project, day),
        "shows_deadline": not booking.is_done and not booking.is_failed,
    }


def _block_warn(booking):
    """The ! a booked block carries, the same on the home page and the schedule.

    ``warn_level`` is 2 for every open session of a problematic project and the
    postponement stage otherwise; ``is_problematic`` rides along so the board's
    script can redraw the marks after a move without asking the server.
    """
    if booking is None:
        return {"is_failed": False, "is_problematic": False, "warn_level": 0, "warn_title": ""}
    return {
        "is_failed": bool(booking.is_failed),
        "is_problematic": bool(booking.project and booking.project.is_problematic),
        "warn_level": warn_level(booking),
        "warn_title": warn_title(booking),
    }


def serialize_slot_card(slot, booking, totals, day):
    """One slot for the dashboard. Slot C deliberately carries no time."""

    project = booking.project if booking else None
    if project is None:
        return {"slot": slot, "project": None}

    is_done = bool(booking.is_done)

    shows_time = slot in TIMED_SLOTS
    tracked_seconds = totals.get(project.id, 0) if shows_time else 0

    return {
        "slot": slot,
        "project": project,
        "is_done": is_done,
        "plan_heading": first_plan_section_title(project.long_goal),
        "shows_time": shows_time,
        # The compact format, not "00:45:00": format_duration() stays for the
        # time-tracking pages, where seconds matter.
        "tracked_label": _minutes_label(tracked_seconds // 60, zero="0m") if shows_time else "",
        **_block_deadline(booking, day),
        **_block_warn(booking),
    }


def _minutes_label(minutes, zero=""):
    """Render a count of minutes as "45m" / "2h" / "1h 20m"."""

    if not minutes:
        return zero
    hours, remaining = divmod(int(minutes), 60)
    if hours and remaining:
        return f"{hours}h {remaining:02d}m"
    if hours:
        return f"{hours}h"
    return f"{remaining}m"


@projects_bp.route("/schedule")
@login_required
def schedule():
    """Rolling weeks of calendar sheets, one card per day, from today on.

    The page shows SCHEDULE_WEEKS weeks - a month - and more when there is
    something to
    show there: a booking further out - a day off pushes them all a day later -
    stretches the window to reach it, and ``weeks`` stretches it by hand.
    """

    today = today_local()
    week_count = weeks_to_cover(current_user.id, today)
    requested = _coerce_int(request.args.get("weeks"))
    if requested is not None:
        week_count = max(week_count, min(requested, MAX_CALENDAR_WEEKS))

    calendar = calendar_weeks(current_user.id, weeks=week_count, start_day=today)
    last_day = calendar[-1][-1][0]
    weeks = _schedule_weeks(calendar, today)
    return render_template(
        "projects/schedule.html",
        weeks=weeks,
        today=today,
        week_count=week_count,
        calendar_window=(today, last_day),
        # Nothing to ask for when every calendar is fresh, or there are none.
        refresh_calendars=has_stale_feeds(current_user),
        grouped_calendars=has_grouped_feeds(current_user.id),
        # Two more weeks per click, up to the point where the page would be all
        # empty sheets.
        more_weeks=min(week_count + 2, MAX_CALENDAR_WEEKS) if week_count < MAX_CALENDAR_WEEKS else None,
        # Where the calendar view's scroll picks up: the Monday after the page.
        next_from=_next_scroll_from(last_day, today),
    )


@projects_bp.route("/schedule/weeks")
@login_required
def schedule_weeks():
    """More weeks for the calendar view, as it is scrolled towards their edge.

    ``from`` is the Monday the new weeks start on - the page hands it out, one
    past its last day - and the answer is the same week sections the page itself
    renders, so every script bound to the board works on them unchanged.
    """

    today = today_local()
    start = parse_slot_date(request.args.get("from"))
    if start is None or start <= today or start.weekday() != 0:
        return jsonify({"ok": False, "message": "Pick a Monday after today."}), 400
    if _weeks_ahead(start, today) >= MAX_SCROLL_WEEKS:
        return jsonify({"ok": True, "html": "", "next_from": None})

    count = _coerce_int(request.args.get("weeks")) or 2
    count = max(1, min(count, 4, MAX_SCROLL_WEEKS - _weeks_ahead(start, today)))
    calendar = calendar_weeks(current_user.id, weeks=count, start_day=start)
    last_day = calendar[-1][-1][0]
    return jsonify(
        {
            "ok": True,
            "html": render_template(
                "projects/_schedule_weeks.html", weeks=_schedule_weeks(calendar, today)
            ),
            "next_from": _next_scroll_from(last_day, today),
        }
    )


def _weeks_ahead(monday, today):
    """Which week ``monday`` starts, counted from this one (0)."""
    return (monday - (today - timedelta(days=today.weekday()))).days // DAYS_PER_WEEK


def _next_scroll_from(last_day, today):
    """The Monday after ``last_day``, or None once the scroll has reached its end."""
    monday = last_day + timedelta(days=1)
    return monday.isoformat() if _weeks_ahead(monday, today) < MAX_SCROLL_WEEKS else None


def _schedule_weeks(calendar, today):
    """The schedule page's weeks, ready for the template - its own and the scroll's.

    One query each for the notes, events and tasks of the whole range, the way
    the bookings already come in one.
    """
    first_day, last_day = calendar[0][0][0], calendar[-1][-1][0]
    notes = notes_from(current_user.id, first_day, last_day)
    # Off the cached copy of each calendar, with no network in sight: re-reading
    # one is the page's job but not the render's, so it happens once the page is
    # up. See the note above [data-calendar-refresh] in the template.
    events = events_by_date(current_user.id, first_day, last_day)
    tasks = tasks_from(current_user.id, first_day, last_day)
    return [
        {
            "label": _week_label(_weeks_ahead(days[0][0] - timedelta(days=days[0][0].weekday()), today)),
            "range_label": _date_range_label(days[0][0], days[-1][0]),
            # The days of this week already behind us: the calendar view keeps
            # their places in the row empty so every column stays one weekday.
            "lead_days": days[0][0].weekday(),
            "days": [
                _serialize_schedule_day(
                    day, booked, today, notes.get(day, ()), events.get(day, ()), tasks.get(day, ())
                )
                for day, booked in days
            ],
        }
        for days in calendar
    ]


@projects_bp.route("/schedule/day-off", methods=["POST"])
@login_required
def schedule_day_off():
    """Free a day by moving it, and everything after it, a day later."""

    payload = request.get_json(silent=True) or request.form
    day = parse_slot_date(payload.get("date"))
    if day is None:
        return jsonify({"ok": False, "message": "Pick a day."}), 400

    ok, message, _moved, late = shift_bookings_forward(current_user.id, day)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409

    # A note on a day still to come is part of that day's plan, so it goes where
    # the blocks go. Nothing can refuse it: unlike a booking, a note has no
    # finished session to stay put for and no slot to collide over.
    shift_notes_forward(current_user.id, day)
    # Open tasks go with the day too; a finished one stays where it was done,
    # the way a finished session does.
    shift_tasks_forward(current_user.id, day)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the schedule."}), 500

    warning = (
        f"The day off pushed past the session deadline: {', '.join(late)}." if late else ""
    )
    return jsonify({"ok": True, "message": message, "warning": warning})


@projects_bp.route("/schedule/archive")
@login_required
def schedule_archive():
    """The same sheets for days that have already been, three weeks at a time.

    Read-only: nothing can be booked, moved or freed in the past, so the blocks
    are shown without the buttons the board carries. ``until`` is the last day on
    the page; the two links are worked out from the page's own edges, which keeps
    the pages gapless whatever weekday the first one starts on.
    """
    today = today_local()
    yesterday = today - timedelta(days=1)
    until = parse_slot_date(request.args.get("until")) or yesterday
    # A page reaching into the future would repeat the schedule page.
    until = min(until, yesterday)

    weeks = past_calendar_weeks(current_user.id, end_day=until)
    # The weeks run newest first, so the page's edges are the oldest week's first
    # day and the newest week's last one.
    first_day = weeks[-1][0][0]
    last_day = weeks[0][-1][0]
    earliest = first_booked_day(current_user.id)

    notes = notes_from(current_user.id, first_day, last_day)
    events = events_by_date(current_user.id, first_day, last_day)
    tasks = tasks_from(current_user.id, first_day, last_day)

    return render_template(
        "projects/archive.html",
        today=today,
        weeks=[
            {
                "label": _past_week_label(week[0][0], today),
                "range_label": _date_range_label(week[0][0], week[-1][0]),
                "days": [
                    _serialize_schedule_day(
                        day, booked, today, notes.get(day, ()), events.get(day, ()), tasks.get(day, ())
                    )
                    for day, booked in week
                ],
            }
            for week in weeks
        ],
        booked_count=sum(
            1 for week in weeks for _, booked in week for entry in booked.values() if entry
        ),
        range_label=_date_range_label(first_day, last_day),
        calendar_window=(first_day, last_day),
        refresh_calendars=has_stale_feeds(current_user),
        # No point offering a page older than the first booking there has ever been.
        earlier_until=first_day - timedelta(days=1)
        if earliest is not None and earliest < first_day
        else None,
        later_until=min(last_day + timedelta(days=ARCHIVE_WEEKS * DAYS_PER_WEEK), yesterday)
        if last_day < yesterday
        else None,
    )


# Calendar weeks, Monday to Sunday: "this week" is whatever is left of it. The
# page runs a month, so the list reaches further than the three weeks it once
# had; anything past it falls back to "In N weeks".
_WEEK_LABELS = ("This week", "Next week", "In two weeks", "In three weeks", "In four weeks")
# The archive counts the other way, and says so from the week's own dates rather
# than its place on the page - "Last week" has to mean last week on every page.
# 0 happens on the newest page every day but a Monday: the days of this week that
# are already behind us.
_PAST_WEEK_LABELS = {
    0: "Earlier this week",
    1: "Last week",
    2: "Two weeks ago",
    3: "Three weeks ago",
}


def _week_label(index):
    return _WEEK_LABELS[index] if index < len(_WEEK_LABELS) else f"In {index} weeks"


def _past_week_label(week_start, today):
    weeks_ago = ((today - timedelta(days=today.weekday())) - week_start).days // DAYS_PER_WEEK
    return _PAST_WEEK_LABELS.get(weeks_ago, f"{weeks_ago} weeks ago")


def _date_range_label(first, last):
    # The current week can be down to a single day, on a Sunday.
    if first == last:
        return first.strftime("%d %b").lstrip("0")
    if first.month == last.month:
        return f"{first.day}–{last.day} {last.strftime('%b')}"
    return f"{first.strftime('%d %b')} – {last.strftime('%d %b')}"


def _serialize_schedule_day(day, booked, today, notes=(), events=(), tasks=()):
    """One calendar sheet: its three slots, its tasks, its lines, and what the header shows.

    "Lines" is the foot of the sheet: the day's events, read off the subscribed
    calendars, and then the notes written here by hand. Two sources, one list -
    what is on that day, whoever put it there.
    """

    slots = [
        {
            "slot": slot,
            "project": booked[slot].project if booked[slot] else None,
            "plan_heading": (
                first_plan_section_title(booked[slot].project.long_goal) if booked[slot] else ""
            ),
            "is_done": bool(booked[slot].is_done) if booked[slot] else False,
            # How often the session has been put off - the count itself, which
            # the board's script needs after a move. How far up the colour scale
            # the block goes is ``warn_level`` (from _block_warn), worked out here
            # rather than in the template so that the class rendered is always
            # one the stylesheet has a colour for, however high the count has run.
            "postponed": booked[slot].postponed_count if booked[slot] else 0,
            # C is the spare slot; it stays visibly secondary once it is filled.
            "is_optional": slot not in TIMED_SLOTS,
            **_block_deadline(booked[slot], day),
            **_block_warn(booked[slot]),
        }
        for slot in SLOTS
    ]
    return {
        "date": day,
        "is_today": day == today,
        "today": today,
        "is_weekend": day.weekday() >= 5,
        "slots": slots,
        "notes": list(notes),
        "events": list(events),
        "tasks": list(tasks),
        "booked_count": sum(1 for entry in slots if entry["project"]),
    }


@projects_bp.route("/timeline-view")
@login_required
def timeline_view():
    """The Projects page: the grouped timeline, or the waiting diagram.

    Two tabs as two URLs (``?view=waiting``) rather than a switch in the page,
    so a banner on a project page can link straight to the diagram.
    """

    if request.args.get("view") == "waiting":
        return render_template(
            "projects/timeline.html",
            view="waiting",
            diagram=_waiting_diagram(current_user.id),
        )

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
        "projects/timeline.html",
        view="timeline",
        projects=projects,
        timeline_groups=timeline_groups,
        timeline_data=timeline_data,
        backlog_group=backlog_group,
        backlog_data=backlog_data,
        project_last_session_labels=last_session_labels,
    )


# The waiting diagram's grid, in pixels. Every card is the same size, so the
# whole layout is worked out here and the template only places what it is given.
WAITING_NODE_WIDTH = 230
WAITING_NODE_HEIGHT = 62
WAITING_COLUMN_GAP = 72
WAITING_ROW_GAP = 14
WAITING_TREE_GAP = 34


def _waiting_diagram(user_id):
    """Every project that waits or is waited for, laid out as trees.

    A project waits for one other at most, so what comes out is a forest: the
    projects waiting for nothing are the roots, on the left, and each column to
    the right is one more step of waiting. A leaf takes the next free row and a
    project is centred on the projects waiting for it - the usual tidy tree, and
    with one parent per card it never needs to cross a line.

    Archived projects are kept: a project still waiting for one that has been
    archived is exactly the thing this page is there to show.
    Returns None when no project is waiting for anything.
    """

    projects = (
        Project.query.filter_by(user_id=user_id)
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    by_id = {project.id: project for project in projects}
    waiting_on = {}
    for project in projects:
        if project.waiting_for_project_id in by_id:
            waiting_on.setdefault(project.waiting_for_project_id, []).append(project)
    involved = [
        project
        for project in projects
        if project.id in waiting_on or project.waiting_for_project_id in by_id
    ]
    if not involved:
        return None

    nodes, placed = [], {}
    cursor = 0

    def place(project, depth):
        nonlocal cursor
        node = {
            "id": project.id,
            "title": project.title,
            "url": url_for("projects.project_detail", project_id=project.id),
            "note": project.waiting_for_note,
            "is_waiting": project.waiting_for_project_id in by_id,
            "is_private": bool(project.is_private),
            "is_archived": bool(project.is_archived),
            "blocking": len(waiting_on.get(project.id, [])),
            "x": depth * (WAITING_NODE_WIDTH + WAITING_COLUMN_GAP),
        }
        # Marked before the children are walked: validation keeps cycles out,
        # but a card is never placed twice even if one got into the data.
        placed[project.id] = node
        nodes.append(node)
        children = [child for child in waiting_on.get(project.id, []) if child.id not in placed]
        if children:
            centres = [place(child, depth + 1) for child in children]
            centre = (centres[0] + centres[-1]) / 2
        else:
            centre = cursor + WAITING_NODE_HEIGHT / 2
            cursor += WAITING_NODE_HEIGHT + WAITING_ROW_GAP
        node["y"] = round(centre - WAITING_NODE_HEIGHT / 2)
        return centre

    roots = [project for project in involved if project.waiting_for_project_id not in by_id]
    # Whatever no root reaches could only be a loop; start it anywhere rather
    # than leave it off the page.
    for project in roots + involved:
        if project.id not in placed:
            place(project, 0)
            cursor += WAITING_TREE_GAP - WAITING_ROW_GAP

    edges = []
    for project in involved:
        parent = placed.get(project.waiting_for_project_id)
        child = placed[project.id]
        if parent is None:
            continue
        x1 = parent["x"] + WAITING_NODE_WIDTH
        y1 = parent["y"] + WAITING_NODE_HEIGHT / 2
        x2 = child["x"]
        y2 = child["y"] + WAITING_NODE_HEIGHT / 2
        bend = WAITING_COLUMN_GAP / 2
        edges.append(
            {
                "path": f"M{x1} {y1:g} C{x1 + bend:g} {y1:g} {x2 - bend:g} {y2:g} {x2 - 2} {y2:g}",
                "is_archived": parent["is_archived"],
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "node_width": WAITING_NODE_WIDTH,
        "node_height": WAITING_NODE_HEIGHT,
        "width": max(node["x"] for node in nodes) + WAITING_NODE_WIDTH,
        "height": max(node["y"] for node in nodes) + WAITING_NODE_HEIGHT,
        "waiting_count": sum(1 for node in nodes if node["is_waiting"]),
    }


@projects_bp.route("/<int:project_id>/schedule-window")
@login_required
def project_schedule_window(project_id):
    """Planner grid for one project: the next seven days and their slots."""

    project = _get_user_project_or_404(project_id)
    return jsonify(
        {
            "ok": True,
            "project": {"id": project.id, "title": project.title},
            **_schedule_window_payload(project.id),
        }
    )


def _schedule_window_payload(project_id):
    """The planner grid plus the one line saying where the project already is.

    The deadline and the title ride along for the question the dialog asks
    before booking a day past it.
    """

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    return {
        "days": schedule_window(current_user.id, project_id),
        "note": booking_note(current_user.id, project_id),
        "project_title": project.title if project else "",
        "deadline_label": project_deadline_label(project),
    }


# What a tag looks like is defined once, in markdown_utils, next to the code that
# paints one into a rendered plan.
# The three kinds of list item the plan editor writes, and nothing else: a tag
# belongs to a thing to do, not to a heading or a paragraph.
PLAN_LIST_ITEM_PATTERN = re.compile(r"^\s*(?:[-*+]\s+(?:\[(?P<checked>[ xX])\]\s+)?|\d+\.\s+)(?P<text>.*\S)\s*$")


@projects_bp.route("/tags")
@login_required
def tags_page():
    """The tag list, as a page of its own.

    It carries no tags: the page arrives with a spinner in it and asks
    ``tags/search`` for them, which is the pass over every plan. A page rather
    than a dialog because a list of everything tagged is somewhere you stay for a
    while - it can be linked to, gone back to, and left open on a phone.
    """

    return render_template("projects/tags.html")


@projects_bp.route("/tags/search")
@login_required
def search_tags():
    """Every #tag in the list items of the active plans, with what carries it.

    Searched on request rather than kept in a table: the tags are plain text in
    the plan, so there is nothing to keep in step - what the plan says now is the
    answer, and a plan edited on another device needs no migration to show up
    here. It costs one pass over the user's plans, which is why the page that
    asks for it opens on a spinner.
    """

    projects = (
        Project.query.filter_by(user_id=current_user.id, is_archived=False)
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    return jsonify({"ok": True, "tags": _collect_tags(projects)})


def _collect_tags(projects):
    """The tags of these projects' plans, alphabetical, each with its items."""

    tags = {}
    for project in projects:
        for text, is_done in _plan_list_items(project.long_goal):
            for name in dict.fromkeys(TAG_PATTERN.findall(text)):
                # "#Shop" and "#shop" are one tag; the first spelling seen names it.
                tag = tags.setdefault(name.lower(), {"name": name, "items": []})
                tag["items"].append(
                    {
                        "project_id": project.id,
                        "project_title": project.title,
                        "text": text,
                        "is_done": is_done,
                        # Safe mode hides a private project's plan; a tagged line
                        # of it listed here would walk straight past that, so the
                        # list is told which rows to cover up.
                        "is_private": bool(project.is_private),
                        # The project page picks the tag out of the plan and scrolls
                        # to it, so the item leads back to itself and not just to
                        # the top of a long plan.
                        "url": url_for(
                            "projects.project_detail", project_id=project.id, tag=tag["name"]
                        ),
                    }
                )

    return [
        {"name": tag["name"], "count": len(tag["items"]), "items": tag["items"]}
        for _, tag in sorted(tags.items())
    ]


def _plan_list_items(markdown):
    """``(text, is_done)`` for every list item in a plan, markers stripped."""

    for line in (markdown or "").splitlines():
        match = PLAN_LIST_ITEM_PATTERN.match(line)
        if match:
            yield match.group("text"), (match.group("checked") or "").lower() == "x"


@projects_bp.route("/schedule/candidates")
@login_required
def slot_candidate_list():
    """Projects offered for one empty slot, for the picker on the home page."""

    slot = (request.args.get("slot") or "").strip().upper()
    day = parse_slot_date(request.args.get("date"))

    if day is None or slot not in SLOTS:
        return jsonify({"ok": False, "message": "Pick a day and a slot."}), 400

    return jsonify(
        {
            "ok": True,
            "date": day.isoformat(),
            "slot": slot,
            "projects": slot_candidates(current_user.id, day, slot),
        }
    )


@projects_bp.route("/<int:project_id>/session-done", methods=["POST"])
@login_required
def toggle_session_done(project_id):
    """Mark today's session for this project as done, or reopen it."""

    project = _get_user_project_or_404(project_id)
    payload = request.get_json(silent=True) or request.form
    done = str(payload.get("done", "1")).lower() not in {"0", "false", "no", "off"}

    ok, message, is_done = set_session_done(current_user.id, project.id, today_local(), done)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to update the session."}), 500

    return jsonify({"ok": True, "message": message, "is_done": is_done})


@projects_bp.route("/<int:project_id>/session-failed", methods=["POST"])
@login_required
def toggle_session_failed(project_id):
    """Mark today's session for this project as failed, or take that back.

    Failing it marks the project problematic, which the page shows as a banner
    - so the answer says whether it now is, and the page reloads to show it.
    """

    project = _get_user_project_or_404(project_id)
    payload = request.get_json(silent=True) or request.form
    failed = str(payload.get("failed", "1")).lower() not in {"0", "false", "no", "off"}

    ok, message, is_failed = set_session_failed(current_user.id, project.id, today_local(), failed)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to update the session."}), 500

    return jsonify(
        {
            "ok": True,
            "message": message,
            "is_failed": is_failed,
            "is_problematic": bool(project.is_problematic),
        }
    )


@projects_bp.route("/schedule/session-done", methods=["POST"])
@login_required
def toggle_block_session_done():
    """Tick off the session in one block, or reopen it - including in the past.

    The other done switch (``toggle_session_done``) is about a project's session
    today, which is the only one the project page and the home page can mean. The
    archive ticks a block on a day that has already been: a session finished on
    Tuesday that nobody marked at the time is still a session finished.
    """

    payload = request.get_json(silent=True) or request.form
    day = parse_slot_date(payload.get("date"))
    slot = (payload.get("slot") or "").strip().upper()
    done = str(payload.get("done", "1")).lower() not in {"0", "false", "no", "off"}

    if day is None:
        return jsonify({"ok": False, "message": "Pick a day."}), 400

    ok, message, is_done = set_block_done(current_user.id, day, slot, done)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to update the session."}), 500

    return jsonify({"ok": True, "message": message, "is_done": is_done})


@projects_bp.route("/schedule/assign", methods=["POST"])
@login_required
def assign_project_slot():
    payload = request.get_json(silent=True) or request.form
    project_id = _coerce_int(payload.get("project_id"))
    slot = (payload.get("slot") or "").strip().upper()
    day = parse_slot_date(payload.get("date"))

    if project_id is None or day is None:
        return jsonify({"ok": False, "message": "Pick a project and a day."}), 400

    ok, message = assign_slot(current_user.id, project_id, day, slot)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409
    warning = deadline_warning(
        Project.query.filter_by(id=project_id, user_id=current_user.id).first(), day
    )

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the schedule."}), 500

    return jsonify(
        {
            "ok": True,
            "message": message,
            "warning": warning,
            **_schedule_window_payload(project_id),
        }
    )


@projects_bp.route("/schedule/move", methods=["POST"])
@login_required
def move_project_slot():
    """Drag and drop on the schedule page: one booking moves onto another block."""

    payload = request.get_json(silent=True) or request.form
    from_day = parse_slot_date(payload.get("from_date"))
    to_day = parse_slot_date(payload.get("to_date"))
    from_slot = (payload.get("from_slot") or "").strip().upper()
    to_slot = (payload.get("to_slot") or "").strip().upper()

    if from_day is None or to_day is None:
        return jsonify({"ok": False, "message": "Pick a block to move from and to."}), 400

    ok, message = move_booking(current_user.id, from_day, from_slot, to_day, to_slot)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409
    db.session.flush()
    warning = move_deadline_warning(current_user.id, from_day, from_slot, to_day, to_slot)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the schedule."}), 500

    return jsonify({"ok": True, "message": message, "warning": warning})


@projects_bp.route("/schedule/clear", methods=["POST"])
@login_required
def clear_project_slot():
    payload = request.get_json(silent=True) or request.form
    slot = (payload.get("slot") or "").strip().upper()
    day = parse_slot_date(payload.get("date"))
    project_id = _coerce_int(payload.get("project_id"))

    if day is None:
        return jsonify({"ok": False, "message": "Pick a day."}), 400

    ok, message = clear_slot(current_user.id, day, slot)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to update the schedule."}), 500

    response = {"ok": True, "message": message}
    if project_id is not None:
        response.update(_schedule_window_payload(project_id))
    return jsonify(response)


@projects_bp.route("/schedule/notes", methods=["POST"])
@login_required
def add_day_note():
    """Write one note against a day - any day, the archive's included.

    The blocks of a past sheet refuse every change, because nothing that has
    already happened can still be planned. A note is the other thing a sheet
    holds: what the day was like, which is usually only written down once it
    has been. So this endpoint takes a date without asking where it falls.
    """

    payload = request.get_json(silent=True) or request.form
    day = parse_slot_date(payload.get("date"))
    if day is None:
        return jsonify({"ok": False, "message": "Pick a day."}), 400

    note, message = add_note(current_user.id, day, payload.get("body"))
    if note is None:
        return jsonify({"ok": False, "message": message}), 400

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the note."}), 500

    return jsonify({"ok": True, "message": message, "note": {"id": note.id, "body": note.body}})


@projects_bp.route("/schedule/notes/update", methods=["POST"])
@login_required
def update_day_note():
    """Rewrite one note, by id. Its day does not change - only the line does."""

    payload = request.get_json(silent=True) or request.form
    note_id = _coerce_int(payload.get("note_id"))
    if note_id is None:
        return jsonify({"ok": False, "message": "Pick a note."}), 400

    note, message = update_note(current_user.id, note_id, payload.get("body"))
    if note is None:
        return jsonify({"ok": False, "message": message}), 400

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the note."}), 500

    return jsonify({"ok": True, "message": message, "note": {"id": note.id, "body": note.body}})


@projects_bp.route("/schedule/notes/delete", methods=["POST"])
@login_required
def delete_day_note():
    """Remove one note, by id. The date is not needed: the note carries it."""

    payload = request.get_json(silent=True) or request.form
    note_id = _coerce_int(payload.get("note_id"))
    if note_id is None:
        return jsonify({"ok": False, "message": "Pick a note."}), 400

    ok, message = delete_note(current_user.id, note_id)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to remove the note."}), 500

    return jsonify({"ok": True, "message": message})


@projects_bp.route("/archived")
@login_required
def archived_projects():
    projects = (
        Project.query.filter_by(user_id=current_user.id, is_archived=True)
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    return render_template(
        "projects/archived.html",
        projects=projects,
        # Archiving leaves the bookings alone, so this page says which of them
        # are still due - one query for the page rather than one per row.
        planned_sessions=planned_session_labels_by_project(current_user.id),
    )


@projects_bp.route("/<int:project_id>/archive", methods=["POST"])
@login_required
def archive_project(project_id):
    project = _get_user_project_or_404(project_id)
    project.is_archived = True
    db.session.commit()
    flash(
        "Project archived — it stays out of the planning, "
        "but the sessions already booked for it stand.",
        "info",
    )
    return redirect(url_for("main.home"))


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


WAITING_NOTE_MAX_LENGTH = 200


def _waits_on(project_id, target_id, waiting_for_by_id):
    """Whether ``project_id`` already waits on ``target_id``, however indirectly.

    Walks the chain of "waiting for" links from the project; the visited set
    keeps a loop already in the data from walking forever.
    """
    seen = set()
    current = project_id
    while current is not None and current not in seen:
        if current == target_id:
            return True
        seen.add(current)
        current = waiting_for_by_id.get(current)
    return False


def _waiting_for_by_id(user_id):
    """Each of the user's projects mapped to the one it waits for (or None)."""

    return dict(
        db.session.query(Project.id, Project.waiting_for_project_id)
        .filter(Project.user_id == user_id)
        .all()
    )


def _waiting_for_choices(project):
    """The projects this one may be set to wait for, alphabetical.

    Not itself, and not one already waiting on it - directly or down a chain -
    since that would make two projects wait for each other and neither could
    ever move. Archived projects are left out, except the one it already waits
    for, so the dialog can show what is set.
    """
    links = _waiting_for_by_id(project.user_id)
    candidates = (
        Project.query.filter(Project.user_id == project.user_id, Project.id != project.id)
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    return [
        candidate
        for candidate in candidates
        if (not candidate.is_archived or candidate.id == project.waiting_for_project_id)
        and not _waits_on(candidate.id, project.id, links)
    ]


PLAN_HEADING_PATTERN = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*\S)\s*$")
# A long plan is a long list to scroll through in a dialog; past this many the
# suggestions stop being a shortcut, and typing the milestone is quicker.
MILESTONE_SUGGESTION_LIMIT = 80


def _plan_milestones(markdown):
    """The headings and the open list items of a plan, in the plan's order.

    Ticked items are left out: a milestone already reached is nothing to wait
    for. Headings stay whatever is under them, since a whole section can be the
    thing another project is held up by.
    """
    milestones = []
    for line in (markdown or "").splitlines():
        heading = PLAN_HEADING_PATTERN.match(line)
        if heading:
            milestones.append(
                {
                    "text": heading.group("text"),
                    "kind": "heading",
                    "level": len(heading.group("hashes")),
                }
            )
            continue
        item = PLAN_LIST_ITEM_PATTERN.match(line)
        if item and (item.group("checked") or "").lower() != "x":
            milestones.append({"text": item.group("text"), "kind": "item", "level": 0})
        if len(milestones) >= MILESTONE_SUGGESTION_LIMIT:
            break
    return milestones


@projects_bp.route("/<int:project_id>/milestones")
@login_required
def project_milestones(project_id):
    """What the waiting dialog suggests as the milestone, off this project's plan.

    Asked for when a project is picked in the dialog rather than rendered into
    every project page: it is another project's plan, and the page would carry
    all of them for a dialog that is rarely opened. Only suggestions - what is
    saved is the text in the field, so rewriting the plan later breaks nothing.
    """
    project = _get_user_project_or_404(project_id)
    return jsonify(
        {
            "ok": True,
            # Safe mode covers a private plan, and these are lines of it: the
            # page is told, and leaves the suggestions out while the mode is on.
            "is_private": bool(project.is_private),
            "milestones": _plan_milestones(project.long_goal),
        }
    )


@projects_bp.route("/<int:project_id>/waiting-for", methods=["POST"])
@login_required
def set_waiting_for(project_id):
    """Put a project on hold until a milestone of another one is reached.

    It leaves the planning the way an archived project does in the one place
    that asks "what still needs a session" - the home page's Not scheduled list -
    but nothing else: it can still be booked, and what is booked stays.
    """
    project = _get_user_project_or_404(project_id)
    target_id = _coerce_int(request.form.get("waiting_for_project_id"))
    note = request.form.get("waiting_for_note", "").strip()
    target = (
        Project.query.filter_by(id=target_id, user_id=current_user.id).first()
        if target_id is not None
        else None
    )

    if target is None:
        flash("Choose the project this one is waiting for.", "danger")
    elif target.id == project.id:
        flash("A project cannot wait for itself.", "danger")
    elif len(note) > WAITING_NOTE_MAX_LENGTH:
        flash(f"Keep the milestone under {WAITING_NOTE_MAX_LENGTH} characters.", "danger")
    elif _waits_on(target.id, project.id, _waiting_for_by_id(current_user.id)):
        flash(
            f"{target.title} is already waiting for this project — "
            "the two would end up waiting for each other.",
            "danger",
        )
    else:
        project.waiting_for_project_id = target.id
        project.waiting_for_note = note
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Failed to save. The database is unavailable for writing.", "danger")
        else:
            flash(
                f"Waiting for {target.title} — out of the Not scheduled list until then.",
                "info",
            )
    return redirect(url_for("projects.project_detail", project_id=project.id))


@projects_bp.route("/<int:project_id>/waiting-for/clear", methods=["POST"])
@login_required
def clear_waiting_for(project_id):
    """Stop waiting: the project is back in the planning.

    Pressed either on the waiting project itself or on the one it waits for,
    when the milestone is reached there - ``next_project_id`` names the page to
    go back to, and only one of the user's own projects is followed.
    """
    project = _get_user_project_or_404(project_id)
    project.waiting_for_project_id = None
    project.waiting_for_note = ""
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to save. The database is unavailable for writing.", "danger")
    else:
        flash(f"{project.title} is no longer waiting — it is back in the planning.", "info")

    next_project = None
    next_id = _coerce_int(request.form.get("next_project_id"))
    if next_id is not None:
        next_project = Project.query.filter_by(id=next_id, user_id=current_user.id).first()
    return redirect(
        url_for("projects.project_detail", project_id=(next_project or project).id)
    )


@projects_bp.route("/<int:project_id>/session-deadline", methods=["POST"])
@login_required
def set_session_deadline(project_id):
    """Set the last day the project's next session should happen on.

    A plan rather than a rule: booking the session later still works, it only
    comes with a warning - and a session already booked past the new deadline
    is left where it is and named in the same way.
    """
    project = _get_user_project_or_404(project_id)
    deadline = parse_slot_date(request.form.get("session_deadline"))
    # The hour is optional: left empty, the deadline is the whole day.
    raw_time = (request.form.get("session_deadline_time") or "").strip()
    deadline_time = _parse_clock_time(raw_time)

    if deadline is None:
        flash("Pick the day the session has to happen by.", "danger")
    elif deadline < today_local():
        flash("A deadline has to be today or later.", "danger")
    elif raw_time and deadline_time is None:
        flash("The hour should look like 14:30.", "danger")
    else:
        project.session_deadline = deadline
        project.session_deadline_time = deadline_time
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Failed to save. The database is unavailable for writing.", "danger")
        else:
            flash(f"Session deadline set to {project_deadline_label(project)}.", "info")
            late = [
                booking
                for booking in _undone_bookings_from_today(project.id)
                if is_after_deadline(project, booking.slot_date)
            ]
            if late:
                flash(
                    f"Already booked for {deadline_label(late[0].slot_date)} in slot {late[0].slot} "
                    "— after the deadline.",
                    "warning",
                )
    return redirect(url_for("projects.project_detail", project_id=project.id))


@projects_bp.route("/<int:project_id>/session-deadline/clear", methods=["POST"])
@login_required
def clear_session_deadline(project_id):
    """Drop the deadline without a session having met it."""
    project = _get_user_project_or_404(project_id)
    project.session_deadline = None
    project.session_deadline_time = None
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to save. The database is unavailable for writing.", "danger")
    else:
        flash("Session deadline removed.", "info")
    return redirect(url_for("projects.project_detail", project_id=project.id))


def _parse_clock_time(value):
    """ "14:30" from a time input as a ``time``, or None when it is not one."""
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _undone_bookings_from_today(project_id):
    """The project's sessions still to be done, from today on, earliest first."""
    return (
        ProjectDaySlot.query.filter(
            ProjectDaySlot.user_id == current_user.id,
            ProjectDaySlot.project_id == project_id,
            ProjectDaySlot.slot_date >= today_local(),
            ProjectDaySlot.is_done.is_(False),
        )
        .order_by(ProjectDaySlot.slot_date.asc())
        .all()
    )


@projects_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_project():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        short_goal = request.form.get("short_goal", "").strip()
        long_goal = request.form.get("long_goal", "").strip()
        is_private = _form_bool("is_private", default=False)

        # Only the name is required: the thoughts and the plan can be written
        # later, on the project's page.
        if not title:
            flash("Please give the project a name.", "danger")
        else:
            project = Project(
                title=title,
                short_goal=short_goal,
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
            return redirect(url_for("main.home"))

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
    # Today's booking, if any - "Done" only means something when there is a
    # session today to finish.
    today_booking = next(
        (
            booking
            for booking in slots_for_date(current_user.id, today_local()).values()
            if booking and booking.project_id == project.id
        ),
        None,
    )

    return render_template(
        "projects/project_detail.html",
        project=project,
        timer_summary=today_project_summary(current_user.id, project.id),
        today_slot=today_booking.slot if today_booking else "",
        today_session_done=bool(today_booking and today_booking.is_done),
        today_session_failed=bool(today_booking and today_booking.is_failed),
        # What archiving left standing, for the banner to name. Only asked for
        # when there is a banner to put it in.
        planned_sessions=planned_session_labels(current_user.id, project.id)
        if project.is_archived
        else [],
        waiting_for_choices=_waiting_for_choices(project),
        waiting_note_max_length=WAITING_NOTE_MAX_LENGTH,
        today=today_local(),
        session_deadline_label=project_deadline_label(project),
    )


@projects_bp.route("/<int:project_id>/statistics")
@login_required
def project_statistics_data(project_id):
    """The Statistics widget's figures, fetched when the widget is asked for.

    Not part of project_detail(): working these out means reading every booking
    and every timer entry of the last three weeks, and the project page is
    opened far more often than the figures are wanted. The widget arrives empty
    and calls this, so the page costs nothing until someone asks.
    """
    project = _get_user_project_or_404(project_id)
    figures = project_statistics(current_user.id, project.id)

    return jsonify(
        {
            "ok": True,
            "statistics": {
                "weeks": figures["weeks"],
                "sessions": figures["sessions"],
                # One decimal: "1.3 a week" says something "1 a week" does not.
                "sessions_per_week_label": f"{figures['sessions_per_week']:.1f}",
                "average_label": _minutes_label(figures["average_seconds"] // 60, zero="0m"),
                "tracked_label": _minutes_label(figures["tracked_seconds"] // 60, zero="0m"),
                "first_day": figures["first_day"].isoformat(),
                "last_day": figures["last_day"].isoformat(),
            },
        }
    )


@projects_bp.route("/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    project = _get_user_project_or_404(project_id)

    if request.method == "GET":
        return redirect(url_for("projects.project_detail", project_id=project.id))

    title = request.form.get("title", "").strip()
    short_goal = request.form.get("short_goal", "").strip()
    long_goal = request.form.get("long_goal", "").strip()
    starred_value = request.form.get("is_starred")
    is_starred = project.is_starred if starred_value is None else starred_value.lower() in {"1", "true", "on", "yes"}
    is_private = _form_bool("is_private", default=project.is_private)
    # Switched by hand in the settings; a failed session sets it and a done one
    # clears it on their own.
    is_problematic = _form_bool("is_problematic", default=project.is_problematic)

    # A navigator.sendBeacon() save fired while the page is being closed: it can't
    # set request headers, so we detect it by a form flag and answer quietly (no
    # flash, no redirect) since the browser discards the response anyway.
    wants_json = _wants_json_response()
    is_beacon = request.form.get("_beacon") == "1"

    # As on creation, the name is the one thing a project cannot be without.
    if not title:
        error_message = "Please give the project a name."
        if wants_json:
            return jsonify({"ok": False, "message": error_message}), 400
        if is_beacon:
            return ("", 400)
        flash(error_message, "danger")
    else:
        project.title = title
        project.short_goal = short_goal
        project.long_goal = long_goal
        project.is_starred = is_starred
        project.is_private = is_private
        project.is_problematic = is_problematic
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            error_message = "Failed to save the project. The database is unavailable for writing."
            if wants_json:
                return jsonify({"ok": False, "message": error_message}), 500
            if is_beacon:
                return ("", 500)
            flash(error_message, "danger")
            return redirect(url_for("projects.project_detail", project_id=project.id))

        success_message = "Project updated successfully."
        if is_beacon:
            return ("", 204)
        if wants_json:
            return jsonify(
                {
                    "ok": True,
                    "message": success_message,
                    "project": {
                        "title": project.title,
                        "short_goal": project.short_goal,
                        "long_goal": project.long_goal,
                        "long_goal_html": str(render_project_markdown(project.long_goal)),
                        "archived_long_goal": project.archived_long_goal or "",
                        "archived_long_goal_html": str(render_project_markdown(project.archived_long_goal or "")),
                        "has_archived_long_goal": bool((project.archived_long_goal or "").strip()),
                        "is_starred": project.is_starred,
                        "is_private": project.is_private,
                        "is_problematic": project.is_problematic,
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
    # SQLite does not enforce the key, so the projects waiting for this one are
    # let go here: with it gone there is nothing left for them to wait on.
    for waiting in project.waited_on_by:
        waiting.waiting_for_project_id = None
        waiting.waiting_for_note = ""
    db.session.delete(project)
    db.session.commit()
    flash("Project deleted.", "info")
    return redirect(url_for("main.home"))


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
