"""Signing in, as JSON.

The forms move into the client for one reason above the others: in an installed
PWA, being thrown out to a server-rendered page leaves the application shell -
different chrome, a full reload, and a page the app-shell cache has no reason to
hold. Everything else about them is unchanged.

What deliberately does NOT move is the lockout. app/lockout.py counts
failures per email address in the database, and it works the same whoever draws
the form; leaving it here means a client cannot decline to enforce it.
"""

from flask import current_app, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError

from .. import lockout
from ..extensions import db
from ..models import User
from .security import issue_token


def describe_wait(seconds):
    """Round the remaining lock up to whole minutes, which is all it promises."""
    if seconds <= 60:
        return "a minute"
    return f"{-(-seconds // 60)} minutes"


def _profile(user):
    return {"username": user.username, "email": user.email}


def register_auth_api(blueprint):
    @blueprint.route("/auth/login", methods=["POST"])
    def login():
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        remember = bool(payload.get("remember"))

        # Both checks happen before the password is looked at, so a locked
        # account cannot be probed by watching how the two answers differ.
        locked_for = lockout.seconds_remaining(email)
        if not locked_for:
            max_attempts = current_app.config.get("LOGIN_MAX_ATTEMPTS", 3)
            if lockout.register_attempt(email) > max_attempts:
                locked_for = lockout.seconds_remaining(email)
        if locked_for:
            return (
                jsonify(
                    {
                        "ok": False,
                        "reason": "locked",
                        "seconds": locked_for,
                        "message": f"Too many attempts. Try again in {describe_wait(locked_for)}.",
                    }
                ),
                429,
            )

        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            return (
                jsonify({"ok": False, "reason": "invalid", "message": "Invalid email or password."}),
                401,
            )

        lockout.clear_failures(email)
        login_user(user, remember=remember)
        return jsonify({"ok": True, "user": _profile(user), "csrf_token": issue_token()})

    @blueprint.route("/auth/register", methods=["POST"])
    def register():
        if not current_app.config.get("REGISTRATION_ENABLED", True):
            return jsonify({"ok": False, "message": "Registration is currently disabled."}), 403

        payload = request.get_json(silent=True) or {}
        username = str(payload.get("username", "")).strip()
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        confirm = str(payload.get("confirm_password", ""))

        if not username or not email or not password:
            message = "All fields are required."
        elif password != confirm:
            message = "Passwords do not match."
        elif User.query.filter_by(username=username).first():
            message = "Username is already taken."
        elif User.query.filter_by(email=email).first():
            message = "An account with that email already exists."
        else:
            message = None

        if message:
            return jsonify({"ok": False, "message": message}), 400

        user = User(username=username, email=email)
        user.set_password(password)
        try:
            db.session.add(user)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify({"ok": False, "message": "Could not create the account."}), 500

        login_user(user)
        return jsonify({"ok": True, "user": _profile(user), "csrf_token": issue_token()})

    @blueprint.route("/auth/change-password", methods=["POST"])
    @login_required
    def change_password():
        payload = request.get_json(silent=True) or {}
        current_password = str(payload.get("current_password", ""))
        new_password = str(payload.get("new_password", ""))
        confirm = str(payload.get("confirm_password", ""))

        if not current_password or not new_password:
            message = "All fields are required."
        elif not current_user.check_password(current_password):
            message = "Your current password is incorrect."
        elif new_password != confirm:
            message = "New passwords do not match."
        elif current_user.check_password(new_password):
            message = "The new password must be different from the current one."
        else:
            message = None

        if message:
            return jsonify({"ok": False, "message": message}), 400

        user = current_user._get_current_object()
        try:
            user.set_password(new_password)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify({"ok": False, "message": "Could not change the password."}), 500

        # The new password invalidated every cookie for this account, this
        # browser's included. Signing back in here leaves the person who made
        # the change logged in and everyone else logged out.
        login_user(user)
        return jsonify(
            {
                "ok": True,
                "csrf_token": issue_token(),
                "message": "Your password has been updated. Other devices were signed out.",
            }
        )

    @blueprint.route("/auth/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        return jsonify({"ok": True})
