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
    CALENDAR_TIMEZONE = os.environ.get("CALENDAR_TIMEZONE", "Europe/Warsaw")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip()
    OPENAI_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT", "30"))
    OPENAI_PROJECT_TIMEOUT = int(os.environ.get("OPENAI_PROJECT_TIMEOUT", "90"))
    OPENAI_TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.7"))
    OPENAI_PROJECT_TEMPERATURE = float(os.environ.get("OPENAI_PROJECT_TEMPERATURE", "0.5"))
    OPENAI_MARKDOWN_TASK = os.environ.get(
        "OPENAI_MARKDOWN_TASK",
        "Answer the user's productivity prompt in Markdown.",
    ).strip()
    OPENAI_PROJECT_TASK = os.environ.get(
        "OPENAI_PROJECT_TASK",
        "Organize this project using the user's prompt. Treat long_goal as the project plan field.",
    ).strip()
