"""
The Integrations page: the calendars whose events show up on the day sheets.

An HTML page with forms rather than a board like the schedule - adding a
calendar is a once-a-year job, and a form that survives a reload with a flash
message is the right shape for it. What the feeds are and how they are read
lives in feeds.py, and the parsing in ical.py.

The one endpoint here that is not part of that page is refresh_due_calendars():
the request the schedule makes once it is on the screen, which is where reading
a calendar is allowed to take its time. See its docstring.
"""

from datetime import timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..projects.slots import parse_slot_date
from ..models import MAX_REFRESH_MINUTES, MIN_REFRESH_MINUTES
from .feeds import (
    MAX_FEEDS_PER_USER,
    add_feed,
    delete_feed,
    events_by_date,
    refresh_due,
    set_feed_enabled,
    user_feeds,
)


integrations_bp = Blueprint("integrations", __name__, url_prefix="/integrations")


@integrations_bp.route("")
@login_required
def integrations_page():
    """Every calendar on the account, with what the last read of it had to say."""

    return render_template(
        "integrations/index.html",
        feeds=user_feeds(current_user.id),
        max_feeds=MAX_FEEDS_PER_USER,
        refresh_minutes=current_user.calendar_refresh_minutes,
        min_refresh_minutes=MIN_REFRESH_MINUTES,
        max_refresh_minutes=MAX_REFRESH_MINUTES,
    )


@integrations_bp.route("/calendars", methods=["POST"])
@login_required
def add_calendar():
    """Subscribe to one iCal address, and read it there and then.

    The first read happens here so the page can answer "does this work" while
    the address is still on the screen, rather than leaving a dead URL looking
    exactly like a live one until the next schedule render.
    """

    feed, message = add_feed(
        current_user.id, request.form.get("name", ""), request.form.get("url", "")
    )
    if feed is None:
        flash(message, "danger")
        return redirect(url_for("integrations.integrations_page"))

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to save the calendar.", "danger")
        return redirect(url_for("integrations.integrations_page"))

    # It is on the list either way; a first read that failed is a warning about
    # the address, not a reason to drop it.
    flash(message, "warning" if feed.last_error else "success")
    return redirect(url_for("integrations.integrations_page"))


@integrations_bp.route("/calendars/<int:feed_id>/delete", methods=["POST"])
@login_required
def remove_calendar(feed_id):
    ok, message = delete_feed(current_user.id, feed_id)
    if not ok:
        flash(message, "danger")
        return redirect(url_for("integrations.integrations_page"))

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to remove the calendar.", "danger")
        return redirect(url_for("integrations.integrations_page"))

    flash(message, "success")
    return redirect(url_for("integrations.integrations_page"))


@integrations_bp.route("/calendars/<int:feed_id>/toggle", methods=["POST"])
@login_required
def toggle_calendar(feed_id):
    """Take a calendar off the sheets without forgetting its address."""

    enabled = request.form.get("enabled", "1") not in {"0", "false", "no", "off"}
    ok, message = set_feed_enabled(current_user.id, feed_id, enabled)
    if not ok:
        flash(message, "danger")
        return redirect(url_for("integrations.integrations_page"))

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to update the calendar.", "danger")
        return redirect(url_for("integrations.integrations_page"))

    flash(message, "success")
    return redirect(url_for("integrations.integrations_page"))


@integrations_bp.route("/calendars/refresh", methods=["POST"])
@login_required
def refresh_calendars():
    """Read every calendar now, rather than when it next falls due."""

    try:
        count = refresh_due(current_user, force=True)
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to save what the calendars said.", "danger")
        return redirect(url_for("integrations.integrations_page"))

    if not count:
        flash("Nothing to read — no calendar is switched on.", "warning")
    else:
        flash(f"Read {count} calendar{'' if count == 1 else 's'}.", "success")
    return redirect(url_for("integrations.integrations_page"))


@integrations_bp.route("/settings", methods=["POST"])
@login_required
def save_settings():
    """How often the calendars are re-read, in minutes.

    Clamped rather than refused: the field is a number box with the same bounds
    on it, so anything outside them arrived some other way and "as close as I
    will go" is a better answer than an error.
    """

    try:
        minutes = int(request.form.get("refresh_minutes", ""))
    except ValueError:
        flash("Give the interval in whole minutes.", "danger")
        return redirect(url_for("integrations.integrations_page"))

    minutes = max(MIN_REFRESH_MINUTES, min(minutes, MAX_REFRESH_MINUTES))
    current_user.calendar_refresh_minutes = minutes

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to save the setting.", "danger")
        return redirect(url_for("integrations.integrations_page"))

    flash(f"Calendars are re-read every {minutes} minutes.", "success")
    return redirect(url_for("integrations.integrations_page"))


@integrations_bp.route("/calendars/refresh-due", methods=["POST"])
@login_required
def refresh_due_calendars():
    """Re-read whatever has gone stale, and hand back the days it changed.

    This is the request the schedule page makes *after* it has rendered, which
    is the whole point of it: reading someone else's calendar takes as long as
    it takes, and none of that may land on the render the reader is waiting on.
    The page therefore draws the cached copy first and patches in what comes
    back here, if anything did.

    ``from``/``to`` are the days the page is showing, so the answer is exactly
    the event lines it has to redraw and nothing else.
    """

    payload = request.get_json(silent=True) or {}
    first_day = parse_slot_date(payload.get("from"))
    last_day = parse_slot_date(payload.get("to"))
    if first_day is None or last_day is None or last_day < first_day:
        return jsonify({"ok": False, "message": "Which days?"}), 400

    try:
        read = refresh_due(current_user)
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save what the calendars said."}), 500

    if not read:
        # Nothing was due after all - another tab may have just done the round.
        return jsonify({"ok": True, "refreshed": 0, "days": None})

    return jsonify(
        {
            "ok": True,
            "refreshed": read,
            "days": _days_payload(current_user.id, first_day, last_day),
        }
    )


def _days_payload(user_id, first_day, last_day):
    """``{"2026-09-15": [{"summary", "time_label", "all_day", "calendar"}]}``.

    The page redraws every sheet in the window from this, so a day that has
    dropped its last event has to be in here as an empty list rather than
    missing - hence every day, not only the ones with something on.
    """
    events = events_by_date(user_id, first_day, last_day)

    days = {}
    day = first_day
    while day <= last_day:
        days[day.isoformat()] = [
            {
                "summary": entry["summary"],
                "time_label": entry["time_label"],
                "all_day": entry["all_day"],
                "calendar": entry["calendar"],
            }
            for entry in events.get(day, ())
        ]
        day += timedelta(days=1)
    return days
