"""Tombstones must be invisible to ordinary reads, by every route into the data."""

from datetime import date


def test_a_deleted_project_is_gone_from_a_plain_query(app, project_factory):
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import Project

    project_factory("keep")
    drop = project_factory("drop")
    drop_id = drop.id

    soft_delete(drop)
    db.session.commit()
    db.session.expunge_all()

    assert [p.title for p in Project.query.all()] == ["keep"]
    assert Project.query.filter_by(id=drop_id).first() is None


def test_a_deleted_slot_is_gone_from_the_relationship(app, user, project_factory):
    """The case a hand-written filter cannot reach: there is no query to edit."""
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import Project, ProjectDaySlot

    project = project_factory()
    project_id = project.id
    kept = ProjectDaySlot(
        user_id=user.id, project_id=project_id, slot_date=date(2026, 9, 3), slot="A"
    )
    removed = ProjectDaySlot(
        user_id=user.id, project_id=project_id, slot_date=date(2026, 9, 4), slot="A"
    )
    db.session.add_all([kept, removed])
    db.session.commit()

    soft_delete(removed)
    db.session.commit()
    db.session.expunge_all()

    reloaded = Project.query.filter_by(id=project_id).one()
    assert [s.slot_date for s in reloaded.day_slots] == [date(2026, 9, 3)]


def test_the_owner_collection_hides_tombstones(app, user, project_factory):
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import User

    user_id = user.id
    project_factory("keep")
    soft_delete(project_factory("drop"))
    db.session.commit()
    db.session.expunge_all()

    account = User.query.filter_by(id=user_id).one()
    assert [p.title for p in account.projects] == ["keep"]


def test_the_pull_path_can_still_see_them(app, project_factory):
    """Reporting deletions is the one job that needs the dead rows."""
    from app.api.revisions import INCLUDE_TOMBSTONES, soft_delete
    from app.extensions import db
    from app.models import Project

    soft_delete(project_factory("drop"))
    db.session.commit()
    db.session.expunge_all()

    rows = (
        db.session.execute(
            db.select(Project).execution_options(**{INCLUDE_TOMBSTONES: True})
        )
        .scalars()
        .all()
    )
    assert [p.deleted_at is not None for p in rows] == [True]
