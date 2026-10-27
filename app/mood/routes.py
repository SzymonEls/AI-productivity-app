"""
The daily mood: one 1-5 score a day, rated from the button beside "Today".

A day has one rating and no more. Pressing the button again opens the same
dialog with the day's score picked, and choosing another rewrites it - the
unique constraint on (user, day) is what makes that an edit rather than a
second row.

The System health widget reads it back as a 7-day average, beside the sessions
ring, and the two-week chart draws that average as a second line. Unlike the
sessions score the window ends today rather than yesterday: a session is still
being worked on today, but a mood rated this morning is already what the day
felt like, and it is the one rating you would want to see move the number.
"""

from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import MOOD_MAX, MOOD_MIN, MoodRating
from ..projects.slots import today_local


mood_bp = Blueprint("mood", __name__, url_prefix="/mood")

# How many days the average on the home page covers, today included.
MOOD_WINDOW_DAYS = 7


def scores_between(user_id, first_day, last_day):
    """Every rated day from ``first_day`` to ``last_day``, as {date: score}."""

    rows = (
        db.session.query(MoodRating.rating_date, MoodRating.score)
        .filter(
            MoodRating.user_id == user_id,
            MoodRating.rating_date >= first_day,
            MoodRating.rating_date <= last_day,
        )
        .all()
    )
    return dict(rows)


def _average(scores, day):
    """The average over the MOOD_WINDOW_DAYS ending on ``day``, and how many were rated.

    Days nobody rated are left out rather than counted as anything: a missing
    rating says nothing about the day.
    """
    rated = [
        scores[day - timedelta(days=back)]
        for back in range(MOOD_WINDOW_DAYS)
        if day - timedelta(days=back) in scores
    ]
    if not rated:
        return None, 0
    return round(sum(rated) / len(rated), 1), len(rated)


def mood_summary(user_id):
    """Today's score and the week's average, as the home page shows them."""

    today = today_local()
    scores = scores_between(user_id, today - timedelta(days=MOOD_WINDOW_DAYS - 1), today)
    average, rated_days = _average(scores, today)
    return {
        "today": scores.get(today),
        "average": average,
        # The ring is filled to the average out of five, so 4.0 reads as 80%.
        "percent": round(average / MOOD_MAX * 100) if average is not None else 0,
        "rated_days": rated_days,
        "window_days": MOOD_WINDOW_DAYS,
    }


def mood_history(user_id, days):
    """The week's average as it stood on each of ``days`` dates, keyed by date.

    One query for the whole stretch, the same way health_history() reads the
    bookings; each date also carries its own score for the chart's tooltip.
    """
    if not days:
        return {}
    scores = scores_between(
        user_id, min(days) - timedelta(days=MOOD_WINDOW_DAYS - 1), max(days)
    )
    history = {}
    for day in days:
        average, rated_days = _average(scores, day)
        history[day] = {"average": average, "rated_days": rated_days, "score": scores.get(day)}
    return history


@mood_bp.route("", methods=["POST"])
@login_required
def rate_today():
    """Set today's mood, or change it if the day has already been rated."""

    payload = request.get_json(silent=True) or request.form
    try:
        score = int(payload.get("score"))
    except (TypeError, ValueError):
        score = None
    if score is None or not MOOD_MIN <= score <= MOOD_MAX:
        return (
            jsonify({"ok": False, "message": f"Pick a number from {MOOD_MIN} to {MOOD_MAX}."}),
            400,
        )

    today = today_local()
    rating = MoodRating.query.filter_by(user_id=current_user.id, rating_date=today).first()
    if rating is None:
        rating = MoodRating(user_id=current_user.id, rating_date=today, score=score)
        db.session.add(rating)
    else:
        rating.score = score

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the mood."}), 500

    return jsonify({"ok": True, "score": score, "summary": mood_summary(current_user.id)})
