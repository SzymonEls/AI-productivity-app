"""Drop the project's frequency note and its daily time target

Revision ID: 20260917_0027
Revises: 20260917_0026
Create Date: 2026-09-17

Both were free-standing intentions nobody scored anything against: the frequency
was a sentence typed once and never read back, and the daily target only ever
produced a percentage on the home page. The Statistics widget on the project page
replaces them by measuring what actually happened instead, and it stores nothing,
so there is no column to put in their place.

``frequency`` was NOT NULL with no default. The downgrade puts it back with a
server_default so existing rows have something to hold, then leaves the default
in place - SQLite rewrites the table to drop one, and a default nobody relies on
is not worth that.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260917_0027'
down_revision = '20260917_0026'
branch_labels = None
depends_on = None


def upgrade():
    columns = _project_columns()
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'daily_target_minutes' in columns:
            batch_op.drop_column('daily_target_minutes')
        if 'frequency' in columns:
            batch_op.drop_column('frequency')


def downgrade():
    columns = _project_columns()
    with op.batch_alter_table('projects', schema=None) as batch_op:
        if 'frequency' not in columns:
            batch_op.add_column(
                sa.Column(
                    'frequency',
                    sa.String(length=255),
                    nullable=False,
                    server_default='Once a week',
                )
            )
        # Nullable, so no server_default is needed: restored rows simply have no target.
        if 'daily_target_minutes' not in columns:
            batch_op.add_column(sa.Column('daily_target_minutes', sa.Integer(), nullable=True))


def _project_columns():
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns('projects')}
