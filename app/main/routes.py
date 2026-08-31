import os

from flask import Blueprint, current_app, redirect, render_template, send_from_directory, url_for
from flask_login import current_user

from ..projects.slots import (
    SLOTS,
    TIMED_SLOTS,
    slots_for_date,
    system_health,
    today_local,
    unscheduled_projects,
)
from ..time_tracking.service import daily_totals_by_project, project_last_session_labels


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    """Today's A/B/C slots, plus the projects with no next session planned.

    There is nothing to show a signed-out visitor, so send them to the login
    page rather than a page of empty placeholders.
    """
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    from ..projects.routes import day_progress, serialize_slot_card

    today = today_local()
    booked = slots_for_date(current_user.id, today)
    # One query for every project's time today, rather than one per slot.
    totals = daily_totals_by_project(current_user.id, today)
    unplanned = unscheduled_projects(current_user.id)
    slot_cards = [serialize_slot_card(slot, booked[slot], totals) for slot in SLOTS]

    return render_template(
        "home.html",
        today=today,
        slot_cards=slot_cards,
        day_progress=day_progress(slot_cards),
        timed_slots=TIMED_SLOTS,
        unplanned_projects=unplanned,
        project_last_session_labels=project_last_session_labels(current_user.id, unplanned),
        # The list is passed in so the health figure reuses it instead of
        # asking for the unscheduled projects a second time.
        health=system_health(current_user.id, unplanned),
    )


@main_bp.route("/app")
@main_bp.route("/app/<path:_client_route>")
def client(_client_route=None):
    """Serve the built client.

    There is no Node process in production: `npm run build` writes a hashed
    bundle into app/static/client and Flask hands out the same index.html for
    every path under /app, leaving the routing to the History API. The Vite dev
    server exists only for hot reload while the frontend is being written.

    This lives at /app until the views cover what the Jinja pages do; then it
    takes over / and those pages go.
    """
    built = os.path.join(current_app.static_folder, "client", "index.html")
    if not os.path.exists(built):
        return (
            "The client has not been built. Run: cd client && npm install && npm run build",
            503,
        )

    response = send_from_directory(
        os.path.join(current_app.static_folder, "client"), "index.html"
    )
    # The shell names hashed assets, so it is the one file that must never be
    # served from a stale cache after a deploy.
    response.headers["Cache-Control"] = "no-cache"
    return response


@main_bp.route("/manifest.webmanifest")
def web_manifest():
    """Serve the PWA manifest from the app root."""

    return send_from_directory(
        current_app.static_folder,
        "manifest.webmanifest",
        mimetype="application/manifest+json",
    )


@main_bp.route("/service-worker.js")
def service_worker():
    """Serve a root-scoped, online-only service worker."""

    response = send_from_directory(
        current_app.static_folder,
        "service-worker.js",
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response
