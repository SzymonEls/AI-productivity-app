"""Add the per-user calendar refresh interval

Revision ID: 20260915_0024
Revises: 20260915_0023
Create Date: 2026-09-15

A server_default so the column can be NOT NULL on the rows that already exist:
every account starts on the half hour the constant in app/models.py names.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260915_0024'
down_revision = '20260915_0023'
branch_labels = None
depends_on = None


def upgrade():
    if _has_column('users', 'calendar_refresh_minutes'):
        return

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'calendar_refresh_minutes',
                sa.Integer(),
                nullable=False,
                server_default='30',
            )
        )


def downgrade():
    if _has_column('users', 'calendar_refresh_minutes'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('calendar_refresh_minutes')


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
