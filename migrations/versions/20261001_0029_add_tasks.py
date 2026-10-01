"""Add tasks: things to do, on a day or on none

Revision ID: 20261001_0029
Revises: 20261001_0028
Create Date: 2026-10-01

A table of its own: a task has a state (done or not) that a day note does not,
and its date is a plan that moves - so neither DayNote nor a booking could hold
it. ``due_date`` is nullable on purpose: a task with no day is still on the
list, just on no sheet.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261001_0029'
down_revision = '20261001_0028'
branch_labels = None
depends_on = None


def upgrade():
    if _has_table('tasks'):
        return

    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('is_done', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('done_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index('ix_tasks_user_due', ['user_id', 'due_date'], unique=False)


def downgrade():
    if not _has_table('tasks'):
        return

    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index('ix_tasks_user_due')

    op.drop_table('tasks')


def _has_table(table_name):
    return table_name in sa.inspect(op.get_bind()).get_table_names()
