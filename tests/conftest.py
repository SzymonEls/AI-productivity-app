"""Shared fixtures.

Every test runs against a temporary SQLite file created by the migrations, not
by ``db.create_all()``. The migrations are the schema of record, and a test
suite built on create_all would happily pass while the migration that has to
run against the real database was broken.
"""

import os
from datetime import date, datetime, timezone

import pytest


@pytest.fixture
def app(tmp_path):
    """A real application on a throwaway database built by the migrations.

    The factory takes a config class, so the test overrides that rather than
    reloading config.py: app/__init__.py binds Config at import time and would
    keep using the old one however many times the module were reloaded.
    """
    from config import Config

    class TestConfig(Config):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SECRET_KEY = "test-secret"
        SECURE_COOKIES = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False
        DEMO_MODE = False
        TESTING = True

    os.environ.pop("SKIP_DB_BOOTSTRAP", None)

    from app import create_app

    application = create_app(TestConfig)

    with application.app_context():
        yield application


@pytest.fixture
def session(app):
    from app.extensions import db

    return db.session


@pytest.fixture
def user(app):
    from app.extensions import db
    from app.models import User

    account = User(username="tester", email="tester@example.com")
    account.set_password("correct horse")
    db.session.add(account)
    db.session.commit()
    return account


@pytest.fixture
def project_factory(app, user):
    from app.extensions import db
    from app.models import Project

    def make(title="A project", **overrides):
        fields = dict(
            user_id=user.id,
            title=title,
            short_goal="goal",
            frequency="daily",
            long_goal="# Plan\n\n- a step #tag\n",
            archived_long_goal="",
        )
        fields.update(overrides)
        project = Project(**fields)
        db.session.add(project)
        db.session.commit()
        return project

    return make


@pytest.fixture
def utc():
    return lambda: datetime.now(timezone.utc)


@pytest.fixture
def today():
    return date.today()
