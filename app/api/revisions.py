"""Stamping writes so another device can find out about them.

Three functions sit between the application and every synchronised row. They
exist because a local copy asks questions a plain write cannot answer: what
changed since I last looked, and what went away while I was offline.

``touch`` marks a row as written. ``soft_delete`` turns a deletion into a fact
that survives long enough to be reported. Both draw from ``next_rev``, the
per-user counter that gives every change a place in one order.

This is a module beside routes.py rather than logic inside it, for the same
reason app/auth/lockout.py is: it is shared by every blueprint that writes, and
inlining it would mean five copies of a rule that has to stay identical.
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from flask import g

from ..extensions import db
from ..models import Project, ProjectTimelineGroup, SyncState
from ..ulid import new_ulid


def utc_now():
    """Naive UTC, matching how every timestamp is already stored."""
    return datetime.now(timezone.utc)


def next_rev(user_id):
    """Return this request's revision number for the user, claiming one if needed.

    Every row written while serving one request shares a number. That is not a
    shortcut: a request commits atomically, so a client either sees all of its
    rows or none of them, and one number per commit keeps the counter - and the
    index that reads it - small.

    The claim is a single UPDATE rather than a read followed by a write. Under
    several Gunicorn workers the read-then-write version lets two requests both
    see 5 and both write 6, handing out one number twice; incrementing inside
    the statement leaves no window between the two halves.
    """
    claimed = g.setdefault("_sync_revisions", {})
    if user_id in claimed:
        return claimed[user_id]

    revision = db.session.execute(
        sa.update(SyncState)
        .where(SyncState.user_id == user_id)
        .values(last_rev=SyncState.last_rev + 1)
        .returning(SyncState.last_rev)
    ).scalar()

    if revision is None:
        # First write this account has ever made. Start at 1, so that a client
        # cursor of 0 means "I have nothing yet" and always trails a real row.
        db.session.add(SyncState(user_id=user_id, last_rev=1, tombstone_floor=0))
        db.session.flush()
        revision = 1

    claimed[user_id] = revision
    return revision


def touch(instance):
    """Stamp a created or updated row so the next pull carries it."""
    if not instance.uid:
        instance.uid = new_ulid()

    instance.rev = next_rev(instance.user_id)
    instance.updated_at = utc_now()
    return instance


def soft_delete(instance):
    """Delete a row without letting it disappear.

    A row that simply vanished is indistinguishable from one that never
    changed, so the other device would never learn of the deletion and would
    push its own copy back. The row therefore stays, carrying nothing but the
    fact that it is gone, until pruning clears it away for good.
    """
    if instance.deleted_at is not None:
        return instance

    instance.deleted_at = utc_now()
    instance.rev = next_rev(instance.user_id)
    _clear_payload(instance)
    _cascade_delete(instance)
    return instance


def _clear_payload(instance):
    """Drop what the user actually wrote, the moment the row dies.

    The tombstone only has to say "this uid is gone". Keeping the text would
    mean a deleted private plan still sat on the server for the whole retention
    window, which is not what deleting it is supposed to mean.
    """
    columns = instance.__table__.columns

    for name in instance.__sync_payload__:
        # NOT NULL columns cannot be nulled, and an empty string reads the same
        # way everywhere the value is displayed.
        setattr(instance, name, None if columns[name].nullable else "")


def _cascade_delete(instance):
    """Carry a deletion to the rows that cannot outlive it.

    SQLAlchemy's delete-orphan cascade does not fire here - nothing is being
    deleted in its sense - so what used to happen through the relationship has
    to happen explicitly, or the children would stay alive locally and be
    invisible to synchronisation.
    """
    if isinstance(instance, Project):
        for entry in list(instance.time_entries):
            # Time entries deliberately outlive their project: they hold a
            # snapshot of the title, so past weeks stay correct. Detaching is
            # still a change other devices need to hear about.
            if entry.ended_at is None:
                entry.ended_at = utc_now()
            entry.project_id = None
            touch(entry)

        for slot in list(instance.day_slots):
            soft_delete(slot)

        for item in list(instance.timeline_items):
            soft_delete(item)

    elif isinstance(instance, ProjectTimelineGroup):
        for item in list(instance.items):
            soft_delete(item)


def live(model):
    """Query for a model, with tombstones filtered out.

    Every read has to exclude deleted rows; going through here means no query
    can forget to and quietly resurrect one on screen.
    """
    return model.query.filter(model.deleted_at.is_(None))
