"""Let a deadline ask for its session a day before

Revision ID: 20261104_0035
Revises: 20261027_0034
Create Date: 2026-11-04

One boolean on projects: whether the next session has to happen at least a
day before the deadline rather than on the deadline day at the latest. It
defaults to false, which is how every deadline set so far has been read, so
the existing ones keep meaning what they meant.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261104_0035'
down_revision = '20261027_0034'
branch_labels = None
depends_on = None


def upgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'session_deadline_day_before' not in columns:
            batch_op.add_column(
                sa.Column(
                    'session_deadline_day_before',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'session_deadline_day_before' in columns:
            batch_op.drop_column('session_deadline_day_before')


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
