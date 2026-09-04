"""Add the identity, revision and tombstone columns synchronisation needs

Revision ID: 20260901_0021
Revises: 20260827_0020
Create Date: 2026-09-01

Three questions a plain autoincrement primary key cannot answer, one column
each. "uid": who am I, when the row was created in a browser with no network
and SQLite never handed out a key? "rev": have you seen this version - a
per-user counter rather than a clock, because two devices disagree about the
time but not about an ordering. "deleted_at": am I gone - a deletion has to be
a fact the next pull can carry, since a row that simply vanished looks exactly
like one that never changed and the other device would push it back.

The ULID generator is inlined rather than imported from app.ulid, for the same
reason 20260823_0019 inlines secrets.token_hex: a migration has to keep working
against the schema it was written for, whatever the application code does next.

uq_project_day_slot changes from a table constraint to a partial unique index.
It has to stop counting tombstones, or freeing a slot would leave it
unbookable - the dead row would still occupy (user_id, slot_date, slot).
"""
import secrets
import time

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260901_0021'
down_revision = '20260827_0020'
branch_labels = None
depends_on = None


SYNC_TABLES = (
    'projects',
    'project_time_entries',
    'project_timeline_groups',
    'project_timeline_items',
    'project_day_slots',
)

# Rows updated per round trip while backfilling. Large enough that a personal
# database finishes in one or two passes, small enough that the write lock is
# never held for an unbounded stretch.
BACKFILL_BATCH = 500

CROCKFORD_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'


def _new_ulid():
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    characters = []
    for _ in range(26):
        characters.append(CROCKFORD_ALPHABET[value & 0x1F])
        value >>= 5
    return ''.join(reversed(characters))


def _sync_columns_table(table_name):
    return sa.table(
        table_name,
        sa.column('id', sa.Integer),
        sa.column('uid', sa.String),
        sa.column('rev', sa.Integer),
    )


def _backfill_sync_columns(connection, table_name):
    """Give every existing row a ULID and a revision the first sync can see.

    The revision has to be 1, not the 0 the column defaults to. A client asks
    for "everything above my cursor", and a brand new client's cursor is 0 - so
    rows left at 0 would sit above nothing, and every project already on the
    server would be invisible to the device that had just been set up.

    Only rows still holding the empty server_default are touched, so running the
    migration twice - or resuming one that was interrupted - is safe.
    """
    table = _sync_columns_table(table_name)

    while True:
        rows = connection.execute(
            sa.select(table.c.id).where(table.c.uid == '').limit(BACKFILL_BATCH)
        ).fetchall()

        if not rows:
            return

        for row in rows:
            connection.execute(
                table.update().where(table.c.id == row.id).values(uid=_new_ulid(), rev=1)
            )


def upgrade():
    for table_name in SYNC_TABLES:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('uid', sa.String(length=26), nullable=False, server_default='')
            )
            batch_op.add_column(
                sa.Column('rev', sa.Integer(), nullable=False, server_default='0')
            )
            batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    op.create_table(
        'sync_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('last_rev', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tombstone_floor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_pruned_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )

    connection = op.get_bind()
    for table_name in SYNC_TABLES:
        _backfill_sync_columns(connection, table_name)

    # Every existing account starts its counter at 1, matching the revision the
    # backfill just wrote, so the next change it makes is numbered above what is
    # already there rather than colliding with it.
    connection.execute(
        sa.text(
            "INSERT INTO sync_states (user_id, last_rev, tombstone_floor,"
            " created_at, updated_at)"
            " SELECT id, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM users"
            " WHERE id NOT IN (SELECT user_id FROM sync_states)"
        )
    )

    # Only now that every row holds a distinct value can the identity be made
    # unique. The day slot table also loses its old table-level constraint here,
    # so that the partial replacement below can take over the same name.
    for table_name in SYNC_TABLES:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            if table_name == 'project_day_slots':
                batch_op.drop_constraint('uq_project_day_slot', type_='unique')

            batch_op.create_unique_constraint(
                f'uq_{table_name}_user_uid', ['user_id', 'uid']
            )
            batch_op.create_index(f'ix_{table_name}_user_rev', ['user_id', 'rev'])
            batch_op.create_index(
                f'ix_{table_name}_user_deleted',
                ['user_id', 'deleted_at'],
                sqlite_where=sa.text('deleted_at IS NOT NULL'),
            )

    op.create_index(
        'uq_project_day_slot',
        'project_day_slots',
        ['user_id', 'slot_date', 'slot'],
        unique=True,
        sqlite_where=sa.text('deleted_at IS NULL'),
    )


def downgrade():
    op.drop_table('sync_states')

    op.drop_index('uq_project_day_slot', table_name='project_day_slots')

    for table_name in SYNC_TABLES:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_index(f'ix_{table_name}_user_deleted')
            batch_op.drop_index(f'ix_{table_name}_user_rev')
            batch_op.drop_constraint(f'uq_{table_name}_user_uid', type_='unique')

            if table_name == 'project_day_slots':
                batch_op.create_unique_constraint(
                    'uq_project_day_slot', ['user_id', 'slot_date', 'slot']
                )

            batch_op.drop_column('deleted_at')
            batch_op.drop_column('rev')
            batch_op.drop_column('uid')
