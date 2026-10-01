"""Let a task repeat

Revision ID: 20261001_0030
Revises: 20261001_0029
Create Date: 2026-10-01

Two nullable columns: the rule a task repeats by, and - on an occurrence written
by ticking off the one before it - the id of that one, so taking the tick back
can take the new occurrence back too. Nothing is backfilled: every existing task
is one that does not repeat.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261001_0030'
down_revision = '20261001_0029'
branch_labels = None
depends_on = None


def upgrade():
    columns = _column_names('tasks')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        if 'repeat_rule' not in columns:
            batch_op.add_column(sa.Column('repeat_rule', sa.String(length=20), nullable=True))
        if 'previous_task_id' not in columns:
            batch_op.add_column(sa.Column('previous_task_id', sa.Integer(), nullable=True))


def downgrade():
    columns = _column_names('tasks')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        if 'previous_task_id' in columns:
            batch_op.drop_column('previous_task_id')
        if 'repeat_rule' in columns:
            batch_op.drop_column('repeat_rule')


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
