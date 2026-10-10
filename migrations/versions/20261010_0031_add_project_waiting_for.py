"""Let a project wait for another one

Revision ID: 20261010_0031
Revises: 20261001_0030
Create Date: 2026-10-10

Two columns on projects: the project this one is waiting for, and the milestone
of it that has to be reached first. Nothing is backfilled: every existing
project is one that waits for nothing.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261010_0031'
down_revision = '20261001_0030'
branch_labels = None
depends_on = None


def upgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'waiting_for_project_id' not in columns:
            batch_op.add_column(
                sa.Column(
                    'waiting_for_project_id',
                    sa.Integer(),
                    sa.ForeignKey('projects.id', name='fk_projects_waiting_for_project_id'),
                    nullable=True,
                )
            )
        if 'waiting_for_note' not in columns:
            batch_op.add_column(
                sa.Column(
                    'waiting_for_note',
                    sa.String(length=200),
                    nullable=False,
                    server_default='',
                )
            )


def downgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'waiting_for_note' in columns:
            batch_op.drop_column('waiting_for_note')
        if 'waiting_for_project_id' in columns:
            batch_op.drop_column('waiting_for_project_id')


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
