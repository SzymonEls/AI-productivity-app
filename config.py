import os
from datetime import timedelta

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_PATH = os.path.join(BASE_DIR, "app", "instance")
INSTANCE_ENV_PATH = os.path.join(INSTANCE_PATH, ".env")
ROOT_ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(INSTANCE_ENV_PATH)
load_dotenv(ROOT_ENV_PATH)


def parse_bool(value, default=False):
    """Parse common environment-style boolean values."""
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    return default


def env_text(name, default):
    """
    Read a text setting, telling "not set" apart from "set to nothing".

    Unlike the usual `os.environ.get(...) or default`, an empty value here means
    the empty string, so a setting can be switched off from the environment.
    """
    value = os.environ.get(name)
    return default if value is None else value.strip()


def normalize_database_url(database_url):
    """Resolve local SQLite database paths relative to the project root."""
    url = make_url(database_url)

    if url.drivername == "sqlite" and url.database not in (None, "", ":memory:"):
        database_path = url.database
        if not os.path.isabs(database_path):
            database_path = os.path.join(BASE_DIR, database_path)
        database_path = os.path.normpath(database_path).replace(os.sep, "/")
        return url.set(database=database_path).render_as_string(hide_password=False)

    return database_url


DEFAULT_DATABASE_URL = f"sqlite:///{os.path.join(INSTANCE_PATH, 'app.db')}"
VERSION_PATH = os.path.join(BASE_DIR, "VERSION")


def read_app_version():
    """Read the release version shipped with the application code."""
    try:
        with open(VERSION_PATH, encoding="utf-8") as version_file:
            return version_file.read().strip()
    except OSError:
        return ""


class Config:
    """Base configuration shared across environments."""

    INSTANCE_PATH = INSTANCE_PATH
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REMEMBER_COOKIE_DURATION = timedelta(
        days=int(os.environ.get("REMEMBER_COOKIE_DAYS", "30"))
    )
    REGISTRATION_ENABLED = parse_bool(os.environ.get("REGISTRATION_ENABLED"), True)
    APP_VERSION = os.environ.get("APP_VERSION", "").strip() or read_app_version()
    DEFAULT_LOGIN_EMAIL = os.environ.get("DEFAULT_LOGIN_EMAIL", "").strip()
    DEFAULT_LOGIN_PASSWORD = os.environ.get("DEFAULT_LOGIN_PASSWORD", "")
    CALENDAR_TIMEZONE = os.environ.get("CALENDAR_TIMEZONE", "Europe/Warsaw")
    # Read-only public demo. Off by default; see app/demo.py.
    DEMO_MODE = parse_bool(os.environ.get("DEMO_MODE"), False)
    DEMO_DOC_PATH = os.environ.get("DEMO_DOC_PATH", "README.md").strip() or "README.md"
    DEMO_DOC_BASE_URL = os.environ.get(
        "DEMO_DOC_BASE_URL", "https://github.com/SzymonEls/AI-productivity-app/blob/main/"
    ).strip()
    DEMO_BLOCK_MESSAGE = (
        os.environ.get("DEMO_BLOCK_MESSAGE", "").strip()
        or "Demo mode - changes are disabled."
    )
    # Empty on purpose means "no banner", so this one distinguishes unset from blank.
    DEMO_BANNER_MESSAGE = env_text(
        "DEMO_BANNER_MESSAGE", "Read-only portfolio demo — nothing you change here is saved."
    )
    # Reserved for a future AI feature; unused by the app today.
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
