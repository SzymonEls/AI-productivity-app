"""Add the per-calendar grouping flag

Revision ID: 20261001_0028
Revises: 20260917_0027
Create Date: 2026-10-01

A server_default so the column can be NOT NULL on the rows that already exist:
every calendar added before this keeps showing one line per event.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261001_0028'
down_revision = '20260917_0027'
branch_labels = None
depends_on = None


def upgrade():
    if _has_column('calendar_feeds', 'is_grouped'):
        return

    with op.batch_alter_table('calendar_feeds', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_grouped',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    if _has_column('calendar_feeds', 'is_grouped'):
        with op.batch_alter_table('calendar_feeds', schema=None) as batch_op:
            batch_op.drop_column('is_grouped')


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
