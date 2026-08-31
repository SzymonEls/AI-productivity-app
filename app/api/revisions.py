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
from sqlalchemy.orm import with_loader_criteria

from ..extensions import db
from ..models import Project, ProjectTimelineGroup, SyncMixin, SyncState
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

    # Core statements against the table, not the ORM entity. This runs from
    # inside before_flush, where the session refuses to flush again and an
    # ORM-enabled statement would try to synchronise one.
    table = SyncState.__table__

    revision = db.session.execute(
        sa.update(table)
        .where(table.c.user_id == user_id)
        .values(last_rev=table.c.last_rev + 1)
        .returning(table.c.last_rev)
    ).scalar()

    if revision is None:
        # First write this account has ever made. Start at 1, so a client cursor
        # of 0 means "I have nothing yet" and always trails a real row.
        db.session.execute(
            sa.insert(table).values(user_id=user_id, last_rev=1, tombstone_floor=0)
        )
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


# Reads that deliberately want the dead rows too - the only one is the pull
# endpoint, whose whole job is to report deletions.
INCLUDE_TOMBSTONES = "include_tombstones"


def register_tombstone_filter(db_):
    """Hide tombstones from every ORM read, everywhere, by default.

    The alternative was a deleted_at filter added by hand to some forty query
    sites. One of them would eventually be missed, and the symptom - a deleted
    project back on screen - would not look like a missing filter.

    It also reaches what a hand-written filter cannot: a lazy load of
    ``project.day_slots`` builds its own query, and there is no line of code
    there to edit.
    """

    @sa.event.listens_for(db_.session, "do_orm_execute")
    def _hide_tombstones(execute_state):
        if not execute_state.is_select:
            return

        # A column load is SQLAlchemy refreshing an object it already holds;
        # filtering there would fail to refresh a row we just deleted ourselves.
        if execute_state.is_column_load or execute_state.is_relationship_load:
            return

        if execute_state.execution_options.get(INCLUDE_TOMBSTONES, False):
            return

        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                SyncMixin,
                lambda cls: cls.deleted_at.is_(None),
                include_aliases=True,
            )
        )

def register_write_stamping(db_):
    """Give every written row a revision, without asking the caller to remember.

    The alternative was a touch() call at every create and update across the
    blueprints. Missing one would not raise anything - the row would simply
    change on the server and never reach the other device, which is the hardest
    kind of bug to notice.

    Rows already carrying a tombstone are left alone: soft_delete() stamped them
    on the way past, and within one request that is the same number anyway.
    """

    @sa.event.listens_for(db_.session, "before_flush")
    def _stamp_writes(session, flush_context, instances):
        for instance in session.new:
            if isinstance(instance, SyncMixin) and instance.deleted_at is None:
                touch(instance)

        for instance in session.dirty:
            if not isinstance(instance, SyncMixin) or instance.deleted_at is not None:
                continue
            if session.is_modified(instance, include_collections=False):
                touch(instance)
