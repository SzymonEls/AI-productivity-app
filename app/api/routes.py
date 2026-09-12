"""JSON API for the macOS menu bar client.

Kept apart from the browser blueprints because it answers to a different
credential: a bearer token instead of the session cookie. The two never mix -
nothing here is reachable with a cookie, and nothing there is reachable with a
token - so the API can stay stable while the pages keep changing.
"""
import secrets
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Project, ProjectTimeEntry, User
from ..projects.slots import SLOTS, slots_for_date, today_local
from ..time_tracking.service import (
    active_entry_for_user,
    app_timezone,
    daily_totals_by_project,
    ensure_utc,
    entry_elapsed_seconds,
    first_plan_section_title,
    format_duration,
    utc_now,
)


api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def _token_required(view):
    """Authenticate by `Authorization: Bearer <token>` instead of the cookie.

    Deliberately not `@login_required`: that one redirects a browser to the
    login page, which a desktop client can only read as a confusing 200.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        user = _user_from_token()
        if user is None:
            return jsonify({"ok": False, "message": "Invalid or missing API token."}), 401

        g.api_user = user
        return view(*args, **kwargs)

    return wrapper


def _user_from_token():
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None

    user = User.query.filter_by(api_token=token).first()
    if user is None or not secrets.compare_digest(token, user.api_token or ""):
        return None

    return user


def _payload():
    """Read the body whether it arrives as JSON or as a form."""
    return request.get_json(silent=True) or request.form


def _get_user_project_or_none(project_id):
    if not project_id:
        return None
    return Project.query.filter_by(id=project_id, user_id=g.api_user.id).first()


def _active_payload(entry):
    """Describe the running entry, or `None` when nothing is running.

    `started_at` goes out as an absolute UTC instant so the client can run its
    own clock off it. Without that, a menu bar showing a live counter would
    have to poll every second just to move a digit.
    """
    if entry is None:
        return None

    elapsed = entry_elapsed_seconds(entry)
    return {
        "entry_id": entry.id,
        "project_id": entry.project_id,
        "project_title": entry.display_project_title,
        "started_at": ensure_utc(entry.started_at).isoformat(),
        "elapsed_seconds": elapsed,
        "elapsed_label": format_duration(elapsed),
        "description": entry.description or "",
    }


def _today_payload(user):
    day = today_local()
    bookings = slots_for_date(user.id, day)
    totals = daily_totals_by_project(user.id, day)
    active = active_entry_for_user(user.id)

    slots = []
    for letter in SLOTS:
        booking = bookings.get(letter)
        project = booking.project if booking else None
        tracked = totals.get(project.id, 0) if project else 0
        slots.append(
            {
                "slot": letter,
                "is_done": bool(booking.is_done) if booking else False,
                "tracked_seconds": tracked,
                "tracked_label": format_duration(tracked),
                "is_running": bool(active and project and active.project_id == project.id),
                "project": None
                if project is None
                else {
                    "id": project.id,
                    "title": project.title,
                    "short_goal": project.short_goal or "",
                    "focus": first_plan_section_title(project.long_goal),
                },
            }
        )

    day_total = sum(totals.values())
    return {
        "ok": True,
        "date": day.isoformat(),
        "timezone": str(app_timezone()),
        "slots": slots,
        "active": _active_payload(active),
        "day_total_seconds": day_total,
        "day_total_label": format_duration(day_total),
    }


@api_bp.route("/me")
@_token_required
def me():
    user = g.api_user
    return jsonify(
        {
            "ok": True,
            "user": {"id": user.id, "username": user.username, "email": user.email},
            "app_version": current_app.config.get("APP_VERSION", "local"),
        }
    )


@api_bp.route("/today")
@_token_required
def today():
    return jsonify(_today_payload(g.api_user))


@api_bp.route("/timer")
@_token_required
def timer():
    return jsonify({"ok": True, "active": _active_payload(active_entry_for_user(g.api_user.id))})


@api_bp.route("/timer/start", methods=["POST"])
@_token_required
def start_timer():
    """Start a project's timer, stopping whatever else was running.

    The web UI refuses this with a 409 and makes you stop the other project
    first. A menu bar has one gesture - you click the project you are on now -
    so here the switch is the answer, and the response says what it displaced.
    """
    user = g.api_user
    project = _get_user_project_or_none(_payload().get("project_id"))
    if project is None:
        return jsonify({"ok": False, "message": "Unknown project."}), 404

    active = active_entry_for_user(user.id)
    if active and active.project_id == project.id:
        return jsonify({"ok": True, "stopped": None, **_today_payload(user)})

    stopped = None
    if active:
        active.ended_at = utc_now()
        stopped = _active_payload(active)

    db.session.add(
        ProjectTimeEntry(
            owner=user,
            project=project,
            project_title_snapshot=project.title,
            started_at=utc_now(),
            description=first_plan_section_title(project.long_goal) or None,
        )
    )

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to start the timer."}), 500

    return jsonify({**_today_payload(user), "stopped": stopped})


@api_bp.route("/timer/stop", methods=["POST"])
@_token_required
def stop_timer():
    user = g.api_user
    active = active_entry_for_user(user.id)
    if active is None:
        return jsonify({"ok": False, "message": "No timer is running."}), 409

    description = (_payload().get("description") or "").strip()
    if description:
        active.description = description
    active.ended_at = utc_now()

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to stop the timer."}), 500

    return jsonify(_today_payload(user))
