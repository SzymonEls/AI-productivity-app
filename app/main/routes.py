from datetime import date

from flask import Blueprint, current_app, render_template, send_from_directory
from flask_login import current_user

from ..models import DailyPlan


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    """Home page with the user's single saved daily plan."""

    daily_plan = None
    if current_user.is_authenticated:
        daily_plan = DailyPlan.query.filter_by(user_id=current_user.id).first()

    return render_template(
        "home.html",
        daily_plan=daily_plan,
        today=date.today(),
    )


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
