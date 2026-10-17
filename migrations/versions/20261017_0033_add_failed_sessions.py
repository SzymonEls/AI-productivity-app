"""Let a session fail, mark its project problematic, and give a deadline an hour

Revision ID: 20261017_0033
Revises: 20261012_0032
Create Date: 2026-10-17

Three columns: an optional time beside a project's session deadline, a
problematic flag on projects, and a failed flag on booked sessions. Nothing is
backfilled: every existing deadline has no hour, no project is problematic and
no session has failed.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261017_0033'
down_revision = '20261012_0032'
branch_labels = None
depends_on = None


def upgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'session_deadline_time' not in columns:
            batch_op.add_column(sa.Column('session_deadline_time', sa.Time(), nullable=True))
        if 'is_problematic' not in columns:
            batch_op.add_column(
                sa.Column('is_problematic', sa.Boolean(), nullable=False, server_default=sa.false())
            )

    columns = _column_names('project_day_slots')
    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        if 'is_failed' not in columns:
            batch_op.add_column(
                sa.Column('is_failed', sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade():
    columns = _column_names('project_day_slots')
    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        if 'is_failed' in columns:
            batch_op.drop_column('is_failed')

    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'is_problematic' in columns:
            batch_op.drop_column('is_problematic')
        if 'session_deadline_time' in columns:
            batch_op.drop_column('session_deadline_time')


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
