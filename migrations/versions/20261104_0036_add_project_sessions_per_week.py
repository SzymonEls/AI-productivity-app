"""Give a project a minimum number of sessions a week

Revision ID: 20261104_0036
Revises: 20261104_0035
Create Date: 2026-11-04

One integer on projects, 1 for every existing project as for every new one:
the fewest sessions a week it should get. A session booked too long after the
one before it is flagged on the schedule and the home page.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261104_0036'
down_revision = '20261104_0035'
branch_labels = None
depends_on = None


def upgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'sessions_per_week' not in columns:
            batch_op.add_column(
                sa.Column('sessions_per_week', sa.Integer(), nullable=False, server_default='1')
            )


def downgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'sessions_per_week' in columns:
            batch_op.drop_column('sessions_per_week')


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
