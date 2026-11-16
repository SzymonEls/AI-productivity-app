"""Let projects be gathered into a group that is planned as one

Revision ID: 20261117_0038
Revises: 20261104_0037
Create Date: 2026-11-17

A group is a project row of its own (``is_group``), so it books, moves and
warns exactly like any other project. Its members point at it with
``group_id``. A group's session remembers which of its members were finished
in it in ``done_member_ids`` on the booking. Nothing is backfilled: every
existing project is an ordinary one in no group.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261117_0038'
down_revision = '20261104_0037'
branch_labels = None
depends_on = None


def upgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'is_group' not in columns:
            batch_op.add_column(
                sa.Column('is_group', sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if 'group_id' not in columns:
            batch_op.add_column(
                sa.Column(
                    'group_id',
                    sa.Integer(),
                    sa.ForeignKey('projects.id', name='fk_projects_group_id'),
                    nullable=True,
                )
            )

    slot_columns = _column_names('project_day_slots')
    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        if 'done_member_ids' not in slot_columns:
            batch_op.add_column(sa.Column('done_member_ids', sa.JSON(), nullable=True))


def downgrade():
    slot_columns = _column_names('project_day_slots')
    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        if 'done_member_ids' in slot_columns:
            batch_op.drop_column('done_member_ids')

    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'group_id' in columns:
            batch_op.drop_column('group_id')
        if 'is_group' in columns:
            batch_op.drop_column('is_group')


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
