import re
from datetime import timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..markdown_utils import TAG_PATTERN, render_project_markdown
from ..models import Project, ProjectTimelineGroup, ProjectTimelineItem
from ..time_tracking.service import (
    daily_totals_by_project,
    first_plan_section_title,
    project_last_session_labels,
    today_project_summary,
    utc_now,
)
from .slots import (
    ARCHIVE_WEEKS,
    DAYS_PER_WEEK,
    MAX_CALENDAR_WEEKS,
    SLOTS,
    TIMED_SLOTS,
    assign_slot,
    booking_note,
    calendar_weeks,
    clear_slot,
    first_booked_day,
    move_booking,
    parse_slot_date,
    past_calendar_weeks,
    schedule_window,
    set_block_done,
    set_session_done,
    shift_bookings_forward,
    slot_candidates,
    slots_for_date,
    today_local,
    unscheduled_projects,
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


def serialize_slot_card(slot, booking, totals):
    """One slot for the dashboard. Slot C deliberately carries no time."""

    project = booking.project if booking else None
    if project is None:
        return {"slot": slot, "project": None}

    is_done = bool(booking.is_done)

    shows_time = slot in TIMED_SLOTS
    tracked_seconds = totals.get(project.id, 0) if shows_time else 0
    target_minutes = project.daily_target_minutes if shows_time else None

    return {
        "slot": slot,
        "project": project,
        "is_done": is_done,
        "plan_heading": first_plan_section_title(project.long_goal),
        "shows_time": shows_time,
        # Same compact format on both sides of the slash: "45m / 2h", not
        # "00:45:00 / 2h". format_duration() stays for the time-tracking pages,
        # where seconds matter.
        "tracked_label": _minutes_label(tracked_seconds // 60, zero="0m") if shows_time else "",
        "target_label": _minutes_label(target_minutes),
        # Raw numbers so the day total can be summed without parsing labels.
        "tracked_minutes": tracked_seconds // 60 if shows_time else 0,
        "target_minutes": target_minutes or 0,
    }


def day_progress(slot_cards):
    """
    How much of today's planned time is done, as a percentage.

    Only slots with a target count, on both sides of the ratio: time spent on a
    project you never set a target for is not progress against a plan, and
    counting it would push the figure past 100% for no clear reason. Returns
    None when nothing is targeted, so the caller can leave the spot empty.
    """
    targeted = [card for card in slot_cards if card.get("target_minutes")]
    if not targeted:
        return None

    tracked = sum(card["tracked_minutes"] for card in targeted)
    target = sum(card["target_minutes"] for card in targeted)

    return {
        "percent": round(tracked / target * 100),
        "tracked_label": _minutes_label(tracked, zero="0m"),
        "target_label": _minutes_label(target),
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

    weeks = [
        {
            "label": _week_label(index),
            "range_label": _date_range_label(days[0][0], days[-1][0]),
            "days": [_serialize_schedule_day(day, booked, today) for day, booked in days],
        }
        for index, days in enumerate(
            calendar_weeks(current_user.id, weeks=week_count, start_day=today)
        )
    ]
    return render_template(
        "projects/schedule.html",
        weeks=weeks,
        today=today,
        week_count=week_count,
        # Two more weeks per click, up to the point where the page would be all
        # empty sheets.
        more_weeks=min(week_count + 2, MAX_CALENDAR_WEEKS) if week_count < MAX_CALENDAR_WEEKS else None,
    )


@projects_bp.route("/schedule/day-off", methods=["POST"])
@login_required
def schedule_day_off():
    """Free a day by moving it, and everything after it, a day later."""

    payload = request.get_json(silent=True) or request.form
    day = parse_slot_date(payload.get("date"))
    if day is None:
        return jsonify({"ok": False, "message": "Pick a day."}), 400

    ok, message, _moved = shift_bookings_forward(current_user.id, day)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the schedule."}), 500

    return jsonify({"ok": True, "message": message})


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

    return render_template(
        "projects/archive.html",
        weeks=[
            {
                "label": _past_week_label(week[0][0], today),
                "range_label": _date_range_label(week[0][0], week[-1][0]),
                "days": [_serialize_schedule_day(day, booked, today) for day, booked in week],
            }
            for week in weeks
        ],
        booked_count=sum(
            1 for week in weeks for _, booked in week for entry in booked.values() if entry
        ),
        range_label=_date_range_label(first_day, last_day),
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


def _serialize_schedule_day(day, booked, today):
    """One calendar sheet: its three slots, plus what the header has to show."""

    slots = [
        {
            "slot": slot,
            "project": booked[slot].project if booked[slot] else None,
            "plan_heading": (
                first_plan_section_title(booked[slot].project.long_goal) if booked[slot] else ""
            ),
            "is_done": bool(booked[slot].is_done) if booked[slot] else False,
            # C is the spare slot; it stays visibly secondary once it is filled.
            "is_optional": slot not in TIMED_SLOTS,
        }
        for slot in SLOTS
    ]
    return {
        "date": day,
        "is_today": day == today,
        "is_weekend": day.weekday() >= 5,
        "slots": slots,
        "booked_count": sum(1 for entry in slots if entry["project"]),
    }


@projects_bp.route("/timeline-view")
@login_required
def timeline_view():
    """The original grouped timeline, kept as a secondary view."""

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
        projects=projects,
        timeline_groups=timeline_groups,
        timeline_data=timeline_data,
        backlog_group=backlog_group,
        backlog_data=backlog_data,
        project_last_session_labels=last_session_labels,
    )


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
    """The planner grid plus the one line saying where the project already is."""

    return {
        "days": schedule_window(current_user.id, project_id),
        "note": booking_note(current_user.id, project_id),
    }


# What a tag looks like is defined once, in markdown_utils, next to the code that
# paints one into a rendered plan.
# The three kinds of list item the plan editor writes, and nothing else: a tag
# belongs to a thing to do, not to a heading or a paragraph.
PLAN_LIST_ITEM_PATTERN = re.compile(r"^\s*(?:[-*+]\s+(?:\[(?P<checked>[ xX])\]\s+)?|\d+\.\s+)(?P<text>.*\S)\s*$")


@projects_bp.route("/tags")
@login_required
def project_tags():
    """Every #tag in the list items of the active plans, with what carries it.

    Searched on request rather than kept in a table: the tags are plain text in
    the plan, so there is nothing to keep in step - what the plan says now is the
    answer, and a plan edited on another device needs no migration to show up
    here. It costs one pass over the user's plans, which is why the dialog that
    asks for it shows a spinner.
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

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the schedule."}), 500

    return jsonify({"ok": True, "message": message, **_schedule_window_payload(project_id)})


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

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the schedule."}), 500

    return jsonify({"ok": True, "message": message})


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


@projects_bp.route("/archived")
@login_required
def archived_projects():
    projects = (
        Project.query.filter_by(user_id=current_user.id, is_archived=True)
        .order_by(func.lower(Project.title).asc())
        .all()
    )
    return render_template("projects/archived.html", projects=projects)


@projects_bp.route("/<int:project_id>/archive", methods=["POST"])
@login_required
def archive_project(project_id):
    project = _get_user_project_or_404(project_id)
    project.is_archived = True
    db.session.commit()
    flash("Project archived.", "info")
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


@projects_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_project():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        short_goal = request.form.get("short_goal", "").strip()
        frequency = request.form.get("frequency", "").strip()
        long_goal = request.form.get("long_goal", "").strip()
        is_private = _form_bool("is_private", default=False)

        if not title or not short_goal or not frequency or not long_goal:
            flash("Please complete all project fields.", "danger")
        else:
            project = Project(
                title=title,
                short_goal=short_goal,
                frequency=frequency,
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
        daily_target_label=_minutes_label(project.daily_target_minutes),
        today_slot=today_booking.slot if today_booking else "",
        today_session_done=bool(today_booking and today_booking.is_done),
    )


@projects_bp.route("/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    project = _get_user_project_or_404(project_id)

    if request.method == "GET":
        return redirect(url_for("projects.project_detail", project_id=project.id))

    title = request.form.get("title", "").strip()
    short_goal = request.form.get("short_goal", "").strip()
    frequency = request.form.get("frequency", "").strip()
    long_goal = request.form.get("long_goal", "").strip()
    starred_value = request.form.get("is_starred")
    is_starred = project.is_starred if starred_value is None else starred_value.lower() in {"1", "true", "on", "yes"}
    is_private = _form_bool("is_private", default=project.is_private)
    # Absent field: leave the target alone (the beacon save posts a subset).
    # Present but empty: the user cleared it, so drop the target.
    if "daily_target_minutes" in request.form:
        raw_target = request.form.get("daily_target_minutes", "").strip()
        daily_target_minutes = _coerce_int(raw_target) if raw_target else None
        if raw_target and (daily_target_minutes is None or daily_target_minutes < 0):
            error_message = "The daily target must be a number of minutes."
            if _wants_json_response():
                return jsonify({"ok": False, "message": error_message}), 400
            flash(error_message, "danger")
            return redirect(url_for("projects.project_detail", project_id=project.id))
    else:
        daily_target_minutes = project.daily_target_minutes

    # A navigator.sendBeacon() save fired while the page is being closed: it can't
    # set request headers, so we detect it by a form flag and answer quietly (no
    # flash, no redirect) since the browser discards the response anyway.
    wants_json = _wants_json_response()
    is_beacon = request.form.get("_beacon") == "1"

    if not title or not short_goal or not frequency:
        error_message = "Please complete all project fields."
        if wants_json:
            return jsonify({"ok": False, "message": error_message}), 400
        if is_beacon:
            return ("", 400)
        flash(error_message, "danger")
    else:
        project.title = title
        project.short_goal = short_goal
        project.frequency = frequency
        project.long_goal = long_goal
        project.is_starred = is_starred
        project.is_private = is_private
        project.daily_target_minutes = daily_target_minutes
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
                        "frequency": project.frequency,
                        "long_goal": project.long_goal,
                        "long_goal_html": str(render_project_markdown(project.long_goal)),
                        "archived_long_goal": project.archived_long_goal or "",
                        "archived_long_goal_html": str(render_project_markdown(project.archived_long_goal or "")),
                        "has_archived_long_goal": bool((project.archived_long_goal or "").strip()),
                        "is_starred": project.is_starred,
                        "is_private": project.is_private,
                        "daily_target_minutes": project.daily_target_minutes,
                        "daily_target_label": _minutes_label(project.daily_target_minutes),
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
                "frequency": project.frequency,
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
                "frequency": project.frequency,
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
                        frequency="-",
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
            "frequency": item.project.frequency if item.project else "",
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
