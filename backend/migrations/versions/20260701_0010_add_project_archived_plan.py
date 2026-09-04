"""Add project archived plan

Revision ID: 20260701_0010
Revises: 20260520_0009
Create Date: 2026-07-01 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260701_0010"
down_revision = "20260520_0009"
branch_labels = None
depends_on = None


def upgrade():
    if _has_column("projects", "archived_long_goal"):
        return

    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("archived_long_goal", sa.Text(), nullable=False, server_default=""))


def downgrade():
    if not _has_column("projects", "archived_long_goal"):
        return

    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("archived_long_goal")


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
