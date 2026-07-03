from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import CalendarSubscription
from .service import fetch_daily_plan, normalize_requested_date


calendar_bp = Blueprint("calendar", __name__)


@calendar_bp.before_request
def require_calendar_enabled():
    if current_app.config.get("CALENDAR_ENABLED", True):
        return None
    message = "The calendar is disabled in this instance's configuration."
    if _wants_json_response():
        return jsonify({"ok": False, "message": message}), 404
    flash(message, "warning")
    return redirect(url_for("main.home"))


@calendar_bp.route("/calendar")
@login_required
def calendar_view():
    """Render the calendar shell while events load asynchronously in the browser."""

    selected_date = normalize_requested_date(request.args.get("date"))
    subscriptions = (
        CalendarSubscription.query.filter_by(user_id=current_user.id)
        .order_by(CalendarSubscription.name.asc())
        .all()
    )

    return render_template(
        "calendar/index.html",
        selected_date=selected_date,
        subscriptions=subscriptions,
        previous_date=selected_date.fromordinal(selected_date.toordinal() - 1),
        next_date=selected_date.fromordinal(selected_date.toordinal() + 1),
    )


@calendar_bp.route("/calendar/events")
@login_required
def calendar_events():
    """Return the rendered event list fragment for the selected day."""

    selected_date = normalize_requested_date(request.args.get("date"))
    subscriptions = (
        CalendarSubscription.query.filter_by(user_id=current_user.id)
        .order_by(CalendarSubscription.name.asc())
        .all()
    )
    events = []
    errors = []

    if subscriptions:
        events, errors = fetch_daily_plan(
            subscriptions=subscriptions,
            target_date=selected_date,
            timezone_name=current_app_timezone(),
        )

    return render_template(
        "calendar/_events.html",
        events=events,
        errors=errors,
        subscriptions=subscriptions,
    )


@calendar_bp.route("/calendar/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Manage saved iCal subscriptions for the current user."""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        ical_url = request.form.get("ical_url", "").strip()

        if not name or not ical_url:
            flash("Enter a calendar name and iCal address.", "danger")
        elif not _looks_like_url(ical_url):
            flash("The iCal address must start with http:// or https://.", "danger")
        else:
            subscription = CalendarSubscription(
                user_id=current_user.id,
                name=name,
                ical_url=ical_url,
            )
            db.session.add(subscription)
            db.session.commit()
            flash("The iCal calendar was added.", "success")
            return redirect(url_for("calendar.settings"))

    subscriptions = (
        CalendarSubscription.query.filter_by(user_id=current_user.id)
        .order_by(CalendarSubscription.name.asc())
        .all()
    )
    return render_template("calendar/settings.html", subscriptions=subscriptions)


@calendar_bp.route("/calendar/settings/<int:subscription_id>/delete", methods=["POST"])
@login_required
def delete_subscription(subscription_id):
    """Delete one saved iCal subscription owned by the current user."""

    subscription = CalendarSubscription.query.filter_by(
        id=subscription_id,
        user_id=current_user.id,
    ).first_or_404()
    db.session.delete(subscription)
    db.session.commit()
    flash(f'Deleted calendar "{subscription.name}".', "info")
    return redirect(url_for("calendar.settings"))


def current_app_timezone():
    return current_app.config.get("CALENDAR_TIMEZONE", "Europe/Warsaw")


def _looks_like_url(value):
    return value.startswith("http://") or value.startswith("https://")


def _wants_json_response():
    return (
        request.headers.get("X-Requested-With") in {"XMLHttpRequest", "fetch"}
        or request.accept_mimetypes.best == "application/json"
    )
