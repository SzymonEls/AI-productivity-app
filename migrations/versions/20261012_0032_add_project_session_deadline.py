"""Give a project's next session a deadline

Revision ID: 20261012_0032
Revises: 20261010_0031
Create Date: 2026-10-12

One nullable date on projects: the last day the next session should happen on.
Nothing is backfilled: every existing project is one without a deadline.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261012_0032'
down_revision = '20261010_0031'
branch_labels = None
depends_on = None


def upgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'session_deadline' not in columns:
            batch_op.add_column(sa.Column('session_deadline', sa.Date(), nullable=True))


def downgrade():
    columns = _column_names('projects')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'session_deadline' in columns:
            batch_op.drop_column('session_deadline')


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
