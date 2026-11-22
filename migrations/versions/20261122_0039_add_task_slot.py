"""Let a task take one of its day's A/B/C blocks in place of a session

Revision ID: 20261122_0039
Revises: 20261117_0038
Create Date: 2026-11-22

``tasks.slot`` is the block letter, or NULL for a task that sits in its day's
list as before. Nothing is backfilled: every existing task stays in the list.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261122_0039'
down_revision = '20261117_0038'
branch_labels = None
depends_on = None


def upgrade():
    columns = _column_names('tasks')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        if 'slot' not in columns:
            batch_op.add_column(sa.Column('slot', sa.String(length=1), nullable=True))


def downgrade():
    columns = _column_names('tasks')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        if 'slot' in columns:
            batch_op.drop_column('slot')


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
