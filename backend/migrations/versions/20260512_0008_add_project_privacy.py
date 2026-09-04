"""Add project and timeline item privacy

Revision ID: 20260512_0008
Revises: 20260512_0007
Create Date: 2026-05-12 12:15:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260512_0008"
down_revision = "20260512_0007"
branch_labels = None
depends_on = None


def upgrade():
    if not _has_column("projects", "is_private"):
        with op.batch_alter_table("projects") as batch_op:
            batch_op.add_column(
                sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false())
            )

    if not _has_column("project_timeline_items", "is_private"):
        with op.batch_alter_table("project_timeline_items") as batch_op:
            batch_op.add_column(
                sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade():
    if _has_column("project_timeline_items", "is_private"):
        with op.batch_alter_table("project_timeline_items") as batch_op:
            batch_op.drop_column("is_private")

    if _has_column("projects", "is_private"):
        with op.batch_alter_table("projects") as batch_op:
            batch_op.drop_column("is_private")


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
