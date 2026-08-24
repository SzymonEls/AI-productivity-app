from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db, limiter
from ..models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_rate_limit():
    """Read the limit per request so configuration stays in one place."""
    return current_app.config.get("LOGIN_RATE_LIMIT", "5 per minute")


def login_email_key():
    """Rate limit the account being guessed at, not only the caller.

    An attacker with a pool of addresses would otherwise get a fresh budget for
    each one while hammering a single account.
    """
    return request.form.get("email", "").strip().lower() or request.remote_addr or ""


def login_attempt_failed(response):
    """Only charge failures: a successful sign-in is the redirect below."""
    return response.status_code != 302


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    if not current_app.config.get("REGISTRATION_ENABLED", True):
        flash("Registration is currently disabled.", "warning")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
        elif password != confirm_password:
            flash("Passwords do not match.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("Username is already taken.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Registration successful. You can now log in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    login_rate_limit,
    methods=["POST"],
    deduct_when=login_attempt_failed,
)
@limiter.limit(
    login_rate_limit,
    methods=["POST"],
    key_func=login_email_key,
    deduct_when=login_attempt_failed,
)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    default_login_email = current_app.config.get("DEFAULT_LOGIN_EMAIL", "")
    default_login_password = current_app.config.get("DEFAULT_LOGIN_PASSWORD", "")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember_me = request.form.get("remember_me") == "on"

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=remember_me)
            flash("Welcome back.", "success")

            next_page = request.args.get("next")
            return redirect(next_page or url_for("main.home"))

        flash("Invalid email or password.", "danger")
        default_login_email = email
        default_login_password = ""

    return render_template(
        "auth/login.html",
        default_login_email=default_login_email,
        default_login_password=default_login_password,
    )


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_password or not new_password:
            flash("All fields are required.", "danger")
        elif not current_user.check_password(current_password):
            flash("Your current password is incorrect.", "danger")
        elif new_password != confirm_password:
            flash("New passwords do not match.", "danger")
        elif current_user.check_password(new_password):
            flash("The new password must be different from the current one.", "danger")
        else:
            user = current_user._get_current_object()
            user.set_password(new_password)
            db.session.commit()
            # The new password invalidated every cookie for this account, this
            # browser's included. Signing back in here leaves the person who
            # made the change logged in and everyone else logged out.
            login_user(user)
            flash("Your password has been updated. Other devices were signed out.", "success")
            return redirect(url_for("main.home"))

    return render_template("auth/change_password.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
