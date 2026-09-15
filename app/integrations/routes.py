"""
The Integrations page: the calendars whose events show up on the day sheets.

An HTML page with forms rather than a board like the schedule - adding a
calendar is a once-a-year job, and a form that survives a reload with a flash
message is the right shape for it. The blueprint holds nothing else: what the
feeds are and how they are read lives in feeds.py, and the parsing in ical.py.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from .feeds import (
    MAX_FEEDS_PER_USER,
    REFRESH_AFTER,
    add_feed,
    delete_feed,
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
        refresh_minutes=int(REFRESH_AFTER.total_seconds() // 60),
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
        count = refresh_due(current_user.id, force=True)
    except SQLAlchemyError:
        db.session.rollback()
        flash("Failed to save what the calendars said.", "danger")
        return redirect(url_for("integrations.integrations_page"))

    if not count:
        flash("Nothing to read — no calendar is switched on.", "warning")
    else:
        flash(f"Read {count} calendar{'' if count == 1 else 's'}.", "success")
    return redirect(url_for("integrations.integrations_page"))
