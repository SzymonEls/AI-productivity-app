"""Proof that a write came from the application, not from another site.

Until now the only thing standing between a logged-in browser and a forged
write was ``SESSION_COOKIE_SAMESITE = "Lax"`` - no token exists anywhere in the
repo. Lax is genuinely most of the defence, but it is one cookie attribute
carrying the whole load, and it stops covering top-level form posts to an
endpoint that changes data.

Now that every write in the application funnels through one JSON endpoint, the
cheap half of the classic pair is worth having: the token goes out in a cookie
the page can read, comes back in a header a cross-origin page cannot set, and
the two are compared. The session itself stays in its HttpOnly cookie, so
nothing long-lived is handed to JavaScript.
"""

import secrets

from flask import jsonify, request, session
from flask_login import current_user

CSRF_SESSION_KEY = "csrf_token"
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

# Anything that can change data. GET and HEAD are read-only here by design.
PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Signing in and signing up cannot present a token: there is no session to have
# issued one. Neither reads or writes anybody's data - the worst a forged
# request achieves is logging the browser in as whoever's password it already
# knew - and both are behind the account lockout.
UNPROTECTED_ENDPOINTS = {"api.login", "api.register"}


def issue_token():
    """Return this session's token, creating one the first time it is asked for."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def attach_token_cookie(response):
    """Publish the token to the page that will have to echo it back."""
    if not current_user.is_authenticated:
        return response

    token = session.get(CSRF_SESSION_KEY)
    if not token:
        return response

    from flask import current_app

    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        # Readable by the page on purpose: echoing it back in a header is the
        # whole mechanism. It is not a credential - the session cookie is, and
        # that one stays HttpOnly.
        httponly=False,
        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE", True)),
        samesite=current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
    )
    return response


def check_token():
    """Refuse a write whose caller could not read the cookie."""
    if request.method not in PROTECTED_METHODS:
        return None
    if request.endpoint in UNPROTECTED_ENDPOINTS:
        return None

    expected = session.get(CSRF_SESSION_KEY)
    presented = request.headers.get(CSRF_HEADER_NAME, "")

    if not expected or not secrets.compare_digest(presented, expected):
        return (
            jsonify(
                {
                    "ok": False,
                    "reason": "csrf",
                    "message": "This request could not be verified. Reload the page.",
                }
            ),
            403,
        )

    return None
