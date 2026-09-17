"""Add the postponement count to a day slot

Revision ID: 20260917_0025
Revises: 20260915_0024
Create Date: 2026-09-17

Counts how often the session has been moved onto a later day, which is what
tints its block on the schedule. server_default is required because the column
is NOT NULL and existing rows need a value - same reason as in 20260809_0018.
Every booking that already exists starts at zero: the moves that happened
before this column were not recorded, and guessing at them would colour blocks
that were never late.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260917_0025'
down_revision = '20260915_0024'
branch_labels = None
depends_on = None


def upgrade():
    if _has_column('project_day_slots', 'postponed_count'):
        return

    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('postponed_count', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade():
    if _has_column('project_day_slots', 'postponed_count'):
        with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
            batch_op.drop_column('postponed_count')


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
