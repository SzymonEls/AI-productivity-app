"""Add project starred flag

Revision ID: 20260425_0003
Revises: 20260422_0002
Create Date: 2026-04-25 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260425_0003"
down_revision = "20260422_0002"
branch_labels = None
depends_on = None


def upgrade():
    if _has_column("projects", "is_starred"):
        return

    op.add_column(
        "projects",
        sa.Column(
            "is_starred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    if _has_column("projects", "is_starred"):
        op.drop_column("projects", "is_starred")


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
