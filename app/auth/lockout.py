"""
Lock sign-in out after too many failures, counted in the database.

The budget belongs to the account being signed in to, not to the address the
request came from. Guessing a password means aiming at one account, and this
follows it wherever it is attempted from - a pool of addresses buys an attacker
nothing. Counting per address as well would mostly punish the legitimate user,
since behind a reverse proxy every request shares one address anyway.
"""

from datetime import datetime, timedelta, timezone

from flask import current_app

from ..extensions import db
from ..models import LoginAttempt


def _settings():
    return (
        current_app.config.get("LOGIN_MAX_ATTEMPTS", 3),
        timedelta(minutes=current_app.config.get("LOGIN_BLOCK_MINUTES", 5)),
    )


def _scope(email):
    """The key an attempt is charged to, or None when there is no account named.

    A submission with no email address cannot be an attempt at any account, so
    there is nothing to count - and no password is ever hashed for it either.
    """
    return f"email:{email}" if email else None


def _utc_now():
    return datetime.now(timezone.utc)


def _as_utc(value):
    # SQLite hands back what it was given without the timezone attached.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def seconds_remaining(email):
    """How long sign-in stays locked, 0 when it is open.

    The lock lifts once the oldest failure still inside the window falls out of
    it, so three failures in quick succession really do cost the full window.
    Checked before anything is written, which keeps a locked-out account from
    being held shut indefinitely by someone who simply keeps knocking.
    """
    scope = _scope(email)
    if scope is None:
        return 0

    max_attempts, window = _settings()
    window_start = _utc_now() - window
    failures = (
        LoginAttempt.query.filter(
            LoginAttempt.scope == scope,
            LoginAttempt.failed_at > window_start,
        )
        .order_by(LoginAttempt.failed_at.asc())
        .all()
    )
    if len(failures) < max_attempts:
        return 0

    unlocks_at = _as_utc(failures[0].failed_at) + window
    return max(int((unlocks_at - _utc_now()).total_seconds()) + 1, 0)


def register_attempt(email):
    """Charge one attempt to the account's budget and report the running total.

    The row is written *before* the count is read, and that order is the whole
    point. Several Gunicorn workers handle sign-ins at the same time, so if each
    one counted first it would see the same total as the others and let its own
    request through - eight workers meant eight attempts got past a limit of
    three. Writing first makes the counts distinct: whichever request inserts
    the n-th row is the one that reads a count of at least n, so no more than
    the allowance can ever read a count inside it, however they interleave.

    Called before the password is known to be wrong, so a sign-in that turns out
    to be correct clears the rows again through ``clear_failures``.
    """
    scope = _scope(email)
    if scope is None:
        return 0

    _, window = _settings()
    now = _utc_now()
    window_start = now - window

    # Rows outside the window can never lock anything again, so this is also the
    # whole of the table's housekeeping - it never grows past one window.
    LoginAttempt.query.filter(LoginAttempt.failed_at <= window_start).delete(
        synchronize_session=False
    )
    db.session.add(LoginAttempt(scope=scope, failed_at=now))
    db.session.commit()

    return LoginAttempt.query.filter(
        LoginAttempt.scope == scope,
        LoginAttempt.failed_at > window_start,
    ).count()


def clear_failures(email):
    """Forget the failures once the right password finally arrives."""
    scope = _scope(email)
    if scope is None:
        return

    LoginAttempt.query.filter(LoginAttempt.scope == scope).delete(
        synchronize_session=False
    )
    db.session.commit()
