"""Migration 0021 against a database that already holds data.

The case a fresh test database cannot show: an installation that has been in
use for months, whose rows the migration has to bring into the protocol without
losing any of them - and without leaving them invisible.
"""

import sqlalchemy as sa
from flask_migrate import downgrade, upgrade


def _rows_at_0020(db):
    """Insert a user and one row per synchronised table, pre-migration."""
    db.session.execute(
        sa.text(
            "INSERT INTO users (username, email, password_hash, session_token, created_at)"
            " VALUES ('old', 'old@example.com', 'x', 'token', CURRENT_TIMESTAMP)"
        )
    )
    user_id = db.session.execute(sa.text("SELECT id FROM users WHERE username='old'")).scalar()

    db.session.execute(
        sa.text(
            "INSERT INTO projects (user_id, title, short_goal, frequency, long_goal,"
            " archived_long_goal, is_starred, is_private, is_archived, created_at, updated_at)"
            " VALUES (:u, 'Long-standing', 'goal', 'daily', '# Plan', '', 0, 0, 0,"
            " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"u": user_id},
    )
    project_id = db.session.execute(sa.text("SELECT id FROM projects")).scalar()

    db.session.execute(
        sa.text(
            "INSERT INTO project_day_slots (user_id, project_id, slot_date, slot, is_done,"
            " created_at, updated_at) VALUES (:u, :p, '2026-08-01', 'A', 0,"
            " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"u": user_id, "p": project_id},
    )
    db.session.execute(
        sa.text(
            "INSERT INTO project_time_entries (user_id, project_id, started_at,"
            " project_title_snapshot, created_at, updated_at)"
            " VALUES (:u, :p, CURRENT_TIMESTAMP, 'Long-standing',"
            " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"u": user_id, "p": project_id},
    )
    db.session.commit()
    return user_id


def test_existing_data_survives_and_becomes_visible(app):
    from app.extensions import db

    downgrade(revision="20260827_0020")
    user_id = _rows_at_0020(db)
    upgrade(revision="20260901_0021")

    counts = {
        table: db.session.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar()
        for table in ("projects", "project_day_slots", "project_time_entries")
    }
    assert counts == {
        "projects": 1,
        "project_day_slots": 1,
        "project_time_entries": 1,
    }, "no row may be lost"

    for table in counts:
        rows = db.session.execute(sa.text(f"SELECT uid, rev FROM {table}")).all()
        for uid, rev in rows:
            assert len(uid) == 26, f"{table} row has no identity"
            # The bug this test exists for: a client's first pull asks for
            # everything above cursor 0, so rows left at revision 0 would sit
            # above nothing and the whole account would look empty.
            assert rev >= 1, f"{table} row would be invisible to a first sync"

    state = db.session.execute(
        sa.text("SELECT user_id, last_rev, tombstone_floor FROM sync_states")
    ).one()
    assert state.user_id == user_id
    assert state.last_rev >= 1, "the counter must not sit below the rows it numbers"
    assert state.tombstone_floor == 0


def test_running_the_migration_twice_changes_nothing(app):
    from app.extensions import db

    downgrade(revision="20260827_0020")
    _rows_at_0020(db)
    upgrade(revision="20260901_0021")

    before = db.session.execute(sa.text("SELECT uid, rev FROM projects")).all()

    upgrade(revision="20260901_0021")
    after = db.session.execute(sa.text("SELECT uid, rev FROM projects")).all()

    assert before == after
