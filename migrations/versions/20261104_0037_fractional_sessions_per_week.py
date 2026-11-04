"""Let a project's sessions a week be a fraction

Revision ID: 20261104_0037
Revises: 20261104_0036
Create Date: 2026-11-04

sessions_per_week goes from an integer to a float, so 0.5 can mean one session
every two weeks and 0.25 one every four. Every value set so far is a whole
number and reads the same as a float.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261104_0037'
down_revision = '20261104_0036'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.alter_column(
            'sessions_per_week',
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default='1',
        )


def downgrade():
    # A fraction has no whole-number equivalent; round it up, so a project
    # held to one session every four weeks comes back as once a week rather
    # than as never.
    op.execute('UPDATE projects SET sessions_per_week = 1 WHERE sessions_per_week < 1')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.alter_column(
            'sessions_per_week',
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            existing_server_default='1',
        )
