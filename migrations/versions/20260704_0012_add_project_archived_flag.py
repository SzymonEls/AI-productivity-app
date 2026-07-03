"""Add project archived flag

Revision ID: 20260704_0012
Revises: 20260703_0011
Create Date: 2026-07-04 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260704_0012"
down_revision = "20260703_0011"
branch_labels = None
depends_on = None


def upgrade():
    if _has_column("projects", "is_archived"):
        return

    op.add_column(
        "projects",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    if _has_column("projects", "is_archived"):
        op.drop_column("projects", "is_archived")


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
