"""The write layer: revisions, tombstones and what a deletion drags with it."""

from datetime import date

import pytest
import sqlalchemy as sa
from flask import g


def end_of_request():
    """Forget this request's claimed revision.

    next_rev() hands every row written while serving one request the same
    number, remembered on ``g``. In production the app context boundary clears
    it; a test lives inside one context, so it has to say where a request ends.
    """
    g.pop("_sync_revisions", None)


def test_touch_assigns_uid_and_increasing_revisions(app, user, project_factory):
    from app.api.revisions import touch
    from app.extensions import db

    first = project_factory("first")
    second = project_factory("second")

    assert len(first.uid) == 26
    assert first.uid != second.uid

    touch(first)
    db.session.commit()
    first_rev = first.rev

    end_of_request()
    touch(second)
    db.session.commit()

    assert first_rev >= 1
    assert second.rev > first_rev


def test_one_revision_is_shared_within_a_request(app, user, project_factory):
    from app.api.revisions import touch
    from app.extensions import db

    one = project_factory("one")
    two = project_factory("two")

    touch(one)
    touch(two)
    db.session.commit()

    assert one.rev == two.rev


def test_soft_delete_keeps_the_row_and_clears_what_was_written(app, project_factory):
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import Project

    project = project_factory("secret plan", long_goal="# Private\n\n- do not keep this\n")
    project_id = project.id

    soft_delete(project)
    db.session.commit()

    stored = db.session.get(Project, project_id)
    assert stored is not None, "the row must survive as a tombstone"
    assert stored.deleted_at is not None
    assert stored.rev >= 1

    # NOT NULL columns cannot be nulled, so they are emptied instead.
    assert stored.title == ""
    assert stored.long_goal == ""
    assert stored.short_goal == ""
    assert "do not keep this" not in (stored.long_goal or "")


def test_soft_delete_is_idempotent(app, project_factory):
    from app.api.revisions import soft_delete
    from app.extensions import db

    project = project_factory()
    soft_delete(project)
    db.session.commit()
    first_deleted_at, first_rev = project.deleted_at, project.rev

    end_of_request()
    soft_delete(project)
    db.session.commit()

    assert project.deleted_at == first_deleted_at
    assert project.rev == first_rev


def test_deleting_a_project_keeps_its_time_entries(app, user, project_factory):
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import ProjectTimeEntry

    project = project_factory("tracked")
    entry = ProjectTimeEntry(
        user_id=user.id,
        project_id=project.id,
        project_title_snapshot=project.title,
        description="an afternoon",
    )
    db.session.add(entry)
    db.session.commit()
    entry_id = entry.id

    soft_delete(project)
    db.session.commit()

    kept = db.session.get(ProjectTimeEntry, entry_id)
    assert kept is not None
    assert kept.deleted_at is None, "history must outlive the project"
    assert kept.project_id is None, "but the link is gone"
    assert kept.project_title_snapshot == "tracked"
    assert kept.display_project_title == "tracked"


def test_deleting_a_project_closes_a_running_timer(app, user, project_factory):
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import ProjectTimeEntry

    project = project_factory()
    running = ProjectTimeEntry(user_id=user.id, project_id=project.id, ended_at=None)
    db.session.add(running)
    db.session.commit()

    soft_delete(project)
    db.session.commit()

    assert running.ended_at is not None


def test_deleting_a_project_cascades_to_slots_and_timeline_items(
    app, user, project_factory
):
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import ProjectDaySlot, ProjectTimelineGroup, ProjectTimelineItem

    project = project_factory()
    group = ProjectTimelineGroup(user_id=user.id, name="Now", position=0)
    db.session.add(group)
    db.session.flush()

    slot = ProjectDaySlot(
        user_id=user.id, project_id=project.id, slot_date=date(2026, 9, 3), slot="B"
    )
    item = ProjectTimelineItem(
        user_id=user.id, group_id=group.id, project_id=project.id, item_type="project"
    )
    db.session.add_all([slot, item])
    db.session.commit()

    soft_delete(project)
    db.session.commit()

    assert slot.deleted_at is not None, "an empty booking is not history worth keeping"
    assert item.deleted_at is not None


def test_deleting_a_group_cascades_to_its_items(app, user, project_factory):
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import ProjectTimelineGroup, ProjectTimelineItem

    group = ProjectTimelineGroup(user_id=user.id, name="Later", position=1)
    db.session.add(group)
    db.session.flush()
    item = ProjectTimelineItem(
        user_id=user.id, group_id=group.id, item_type="note", title="a note"
    )
    db.session.add(item)
    db.session.commit()

    soft_delete(group)
    db.session.commit()

    assert item.deleted_at is not None
    assert item.title is None, "a note's text is what the user wrote"


def test_a_tombstoned_booking_frees_the_slot(app, user, project_factory):
    """The partial unique index, from the outside.

    A plain constraint would leave the dead row occupying (user, date, slot),
    so freeing a slot would make it permanently unbookable.
    """
    from app.api.revisions import soft_delete
    from app.extensions import db
    from app.models import ProjectDaySlot

    first = project_factory("first")
    second = project_factory("second")
    when = date(2026, 9, 3)

    booking = ProjectDaySlot(user_id=user.id, project_id=first.id, slot_date=when, slot="A")
    db.session.add(booking)
    db.session.commit()

    soft_delete(booking)
    db.session.commit()

    replacement = ProjectDaySlot(
        user_id=user.id, project_id=second.id, slot_date=when, slot="A"
    )
    db.session.add(replacement)
    db.session.commit()

    assert replacement.id != booking.id


def test_two_live_bookings_cannot_share_a_slot(app, user, project_factory):
    from app.extensions import db
    from app.models import ProjectDaySlot

    first = project_factory("first")
    second = project_factory("second")
    when = date(2026, 9, 4)

    db.session.add(
        ProjectDaySlot(user_id=user.id, project_id=first.id, slot_date=when, slot="B")
    )
    db.session.commit()

    db.session.add(
        ProjectDaySlot(user_id=user.id, project_id=second.id, slot_date=when, slot="B")
    )
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()
