"""
Lock sign-in out after too many failures, counted in the database.

Two budgets are spent by every failure: one for the address the request came
from, one for the account it was aimed at. The first stops one machine working
through passwords; the second stops a pool of addresses working through one
account. Either running out locks sign-in for the whole window.
"""

from datetime import datetime, timedelta, timezone

from flask import current_app, request

from ..extensions import db
from ..models import LoginAttempt


def _settings():
    return (
        current_app.config.get("LOGIN_MAX_ATTEMPTS", 3),
        timedelta(minutes=current_app.config.get("LOGIN_BLOCK_MINUTES", 5)),
    )


def _scopes(email):
    """The two keys one attempt is charged to."""
    scopes = [f"ip:{request.remote_addr or 'unknown'}"]
    if email:
        scopes.append(f"email:{email}")
    return scopes


def _utc_now():
    return datetime.now(timezone.utc)


def _as_utc(value):
    # SQLite hands back what it was given without the timezone attached.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def seconds_remaining(email):
    """How long sign-in stays locked, 0 when it is open.

    The lock lifts once the oldest failure still inside the window falls out of
    it, so three failures in quick succession really do cost the full window.
    """
    max_attempts, window = _settings()
    window_start = _utc_now() - window

    longest = 0
    for scope in _scopes(email):
        failures = (
            LoginAttempt.query.filter(
                LoginAttempt.scope == scope,
                LoginAttempt.failed_at > window_start,
            )
            .order_by(LoginAttempt.failed_at.asc())
            .all()
        )
        if len(failures) < max_attempts:
            continue

        unlocks_at = _as_utc(failures[0].failed_at) + window
        longest = max(longest, int((unlocks_at - _utc_now()).total_seconds()) + 1)

    return max(longest, 0)


def record_failure(email):
    """Charge one failure to both budgets."""
    _, window = _settings()
    now = _utc_now()

    # Rows outside the window can never lock anything again, so this is also
    # the whole of the table's housekeeping - it never grows past the failures
    # of one window.
    LoginAttempt.query.filter(LoginAttempt.failed_at <= now - window).delete(
        synchronize_session=False
    )
    for scope in _scopes(email):
        db.session.add(LoginAttempt(scope=scope, failed_at=now))
    db.session.commit()


def clear_failures(email):
    """Forget the failures once the right password finally arrives."""
    scopes = _scopes(email)
    LoginAttempt.query.filter(LoginAttempt.scope.in_(scopes)).delete(
        synchronize_session=False
    )
    db.session.commit()
