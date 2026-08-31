"""Scheduling behaviour that the tombstone change had to leave untouched.

move_booking in particular was rewritten: swapping two bookings used to delete
the displaced row and insert a replacement, which under synchronisation would
cost it its identity. These tests pin the behaviour, not the implementation.
"""

from datetime import date, timedelta

import pytest


@pytest.fixture
def book(app, user):
    from app.extensions import db
    from app.models import ProjectDaySlot

    def make(project, day, slot, is_done=False):
        booking = ProjectDaySlot(
            user_id=user.id,
            project_id=project.id,
            slot_date=day,
            slot=slot,
            is_done=is_done,
        )
        db.session.add(booking)
        db.session.commit()
        return booking

    return make


def test_moving_into_a_free_slot(app, user, project_factory, book):
    from app.extensions import db
    from app.projects.slots import move_booking, slots_for_date

    project = project_factory("alpha")
    day = date.today() + timedelta(days=3)
    book(project, day, "A")

    ok, message = move_booking(user.id, day, "A", day, "B")
    db.session.commit()

    assert ok, message
    filled = slots_for_date(user.id, day)
    assert filled["A"] is None
    assert filled["B"].project_id == project.id


def test_swapping_two_bookings_keeps_both_identities(app, user, project_factory, book):
    """The point of the rewrite: a swap must not destroy and re-create a row."""
    from app.extensions import db
    from app.projects.slots import move_booking, slots_for_date

    alpha = project_factory("alpha")
    beta = project_factory("beta")
    day = date.today() + timedelta(days=3)
    user_id = user.id

    first = book(alpha, day, "A")
    second = book(beta, day, "B")
    first_uid, second_uid = first.uid, second.uid

    ok, message = move_booking(user_id, day, "A", day, "B")
    db.session.commit()
    db.session.expunge_all()

    assert ok, message
    assert "Swapped" in message

    filled = slots_for_date(user_id, day)
    assert filled["A"].project.title == "beta"
    assert filled["B"].project.title == "alpha"
    # Same two rows, changed places - no tombstone, no new uid.
    assert {filled["A"].uid, filled["B"].uid} == {first_uid, second_uid}


def test_a_swap_leaves_no_tombstone_behind(app, user, project_factory, book):
    from app.api.revisions import INCLUDE_TOMBSTONES
    from app.extensions import db
    from app.models import ProjectDaySlot
    from app.projects.slots import move_booking

    alpha = project_factory("alpha")
    beta = project_factory("beta")
    day = date.today() + timedelta(days=3)
    book(alpha, day, "A")
    book(beta, day, "B")

    move_booking(user.id, day, "A", day, "B")
    db.session.commit()

    dead = db.session.execute(
        db.select(ProjectDaySlot)
        .where(ProjectDaySlot.deleted_at.is_not(None))
        .execution_options(**{INCLUDE_TOMBSTONES: True})
    ).scalars().all()
    assert dead == []


def test_done_is_dropped_when_a_booking_changes_day(app, user, project_factory, book):
    from app.extensions import db
    from app.projects.slots import move_booking, slots_for_date

    project = project_factory()
    day = date.today() + timedelta(days=2)
    later = day + timedelta(days=1)
    book(project, day, "A", is_done=True)

    move_booking(user.id, day, "A", later, "A")
    db.session.commit()

    assert slots_for_date(user.id, later)["A"].is_done is False


def test_clearing_a_slot_frees_it_and_leaves_a_tombstone(app, user, project_factory, book):
    from app.api.revisions import INCLUDE_TOMBSTONES
    from app.extensions import db
    from app.models import ProjectDaySlot
    from app.projects.slots import clear_slot, slots_for_date

    project = project_factory()
    day = date.today() + timedelta(days=4)
    book(project, day, "C")

    ok, _ = clear_slot(user.id, day, "C")
    db.session.commit()

    assert ok
    assert slots_for_date(user.id, day)["C"] is None

    dead = db.session.execute(
        db.select(ProjectDaySlot).execution_options(**{INCLUDE_TOMBSTONES: True})
    ).scalars().all()
    assert len(dead) == 1 and dead[0].deleted_at is not None


def test_a_cleared_slot_can_be_booked_again(app, user, project_factory, book):
    from app.extensions import db
    from app.projects.slots import assign_slot, clear_slot, slots_for_date

    alpha = project_factory("alpha")
    beta = project_factory("beta")
    day = date.today() + timedelta(days=5)

    book(alpha, day, "A")
    clear_slot(user.id, day, "A")
    db.session.commit()

    ok, message = assign_slot(user.id, beta.id, day, "A")
    db.session.commit()

    assert ok, message
    assert slots_for_date(user.id, day)["A"].project.title == "beta"


def test_day_off_pushes_bookings_forward(app, user, project_factory, book):
    from app.extensions import db
    from app.projects.slots import shift_bookings_forward, slots_for_date

    alpha = project_factory("alpha")
    beta = project_factory("beta")
    first = date.today() + timedelta(days=2)
    second = first + timedelta(days=1)

    book(alpha, first, "A")
    book(beta, second, "A")

    ok, _, moved = shift_bookings_forward(user.id, first, days=1)
    db.session.commit()

    assert ok
    assert moved == 2
    assert slots_for_date(user.id, first)["A"] is None
    assert slots_for_date(user.id, second)["A"].project.title == "alpha"
    assert slots_for_date(user.id, second + timedelta(days=1))["A"].project.title == "beta"


def test_a_finished_session_does_not_move_on_a_day_off(app, user, project_factory, book):
    from app.extensions import db
    from app.projects.slots import shift_bookings_forward, slots_for_date

    project = project_factory()
    day = date.today() + timedelta(days=2)
    book(project, day, "A", is_done=True)

    shift_bookings_forward(user.id, day, days=1)
    db.session.commit()

    assert slots_for_date(user.id, day)["A"] is not None, "done belongs to the day it happened"
