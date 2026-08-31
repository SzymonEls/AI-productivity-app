"""Clearing tombstones away once no device can still need them."""

from datetime import timedelta

import click
import sqlalchemy as sa
from flask import current_app

from ..extensions import db
from ..models import SyncState
from .protocol import ENTITIES
from .revisions import INCLUDE_TOMBSTONES, utc_now

# SQLite has one writer, and a long transaction blocks the others. At three
# workers and one account that is theoretical, but an unbounded delete has no
# business on the request path. A backlog simply finishes over the coming days -
# safe, because the floor only ever moves as far as the deleting actually got.
PRUNE_BATCH = 500

# How often the request path bothers to look, not how long a tombstone lives.
PRUNE_INTERVAL = timedelta(days=1)


def retention_days():
    return int(current_app.config.get("TOMBSTONE_RETENTION_DAYS", 90))


def prune_tombstones(user_id, force=False, limit=PRUNE_BATCH):
    """Delete expired tombstones for one account. Returns how many went.

    Called from push rather than pull: push already holds a write transaction
    and is what creates tombstones in the first place, whereas pull is a GET,
    and writing to the database during a GET is the habit ARCHITECTURE.md
    already lists as a thing to be surprised by.
    """
    state = db.session.execute(
        sa.select(SyncState).where(SyncState.user_id == user_id)
    ).scalar_one_or_none()

    if state is None:
        return 0

    now = utc_now().replace(tzinfo=None)

    if not force and state.last_pruned_at and now - state.last_pruned_at < PRUNE_INTERVAL:
        return 0

    cutoff = now - timedelta(days=retention_days())
    removed = 0
    highest_rev = state.tombstone_floor or 0

    for entity in ENTITIES.values():
        model = entity.model
        doomed = db.session.execute(
            sa.select(model.id, model.rev)
            .where(
                model.user_id == user_id,
                model.deleted_at.is_not(None),
                model.deleted_at < cutoff,
            )
            .order_by(model.rev)
            .limit(limit)
            .execution_options(**{INCLUDE_TOMBSTONES: True})
        ).all()

        if not doomed:
            continue

        db.session.execute(
            sa.delete(model).where(model.id.in_([row.id for row in doomed]))
        )
        removed += len(doomed)
        highest_rev = max(highest_rev, max(row.rev for row in doomed))

    # The floor rises only to what was actually cleared. A client whose cursor
    # still sits above it can be answered with a difference; one below it is
    # told to fetch everything, because the deletions it missed are gone.
    state.tombstone_floor = highest_rev
    state.last_pruned_at = now
    db.session.commit()

    return removed


def register_pruning_command(app):
    @app.cli.command("prune-tombstones")
    @click.option("--all-users", is_flag=True, help="Every account, not just one.")
    @click.option("--user-id", type=int, default=None)
    def prune_command(all_users, user_id):
        """Clear away deleted rows past their retention window."""
        if user_id is not None:
            targets = [user_id]
        elif all_users:
            targets = list(
                db.session.execute(sa.select(SyncState.user_id)).scalars().all()
            )
        else:
            raise click.UsageError("Pass --user-id or --all-users.")

        for target in targets:
            # No throttle and no batch cap: this is someone asking for it.
            removed = prune_tombstones(target, force=True, limit=None)
            click.echo(f"user {target}: {removed} tombstones removed")
