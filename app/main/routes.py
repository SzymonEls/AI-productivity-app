from datetime import date

from flask import Blueprint, render_template
from flask_login import current_user

from ..ai.service import MARKDOWN_RESPONSE, is_openai_configured
from ..models import AIPlan


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    """Home page with the pinned daily AI markdown response."""

    latest_plan = None
    if current_user.is_authenticated:
        latest_plan = (
            AIPlan.query.filter_by(user_id=current_user.id)
            .filter(AIPlan.plan_type.in_([MARKDOWN_RESPONSE, "daily_plan", "manual_daily_plan"]))
            .filter_by(is_pinned=True)
            .order_by(AIPlan.created_at.desc())
            .first()
        )
        if latest_plan is None:
            latest_plan = (
                AIPlan.query.filter_by(user_id=current_user.id)
                .filter(AIPlan.plan_type.in_([MARKDOWN_RESPONSE, "daily_plan", "manual_daily_plan"]))
                .order_by(AIPlan.created_at.desc())
                .first()
            )

    return render_template(
        "home.html",
        latest_plan=latest_plan,
        is_openai_ready=current_user.is_authenticated and is_openai_configured(),
        today=date.today(),
    )
