"""Add the done flag to a day slot

Revision ID: 20260809_0018
Revises: 20260809_0017
Create Date: 2026-08-09

Marks one day's session as finished. server_default is required because the
column is NOT NULL and existing rows need a value - same reason as in
20260704_0012.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260809_0018'
down_revision = '20260809_0017'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_done', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        batch_op.drop_column('is_done')
