"""Add is_backlog flag to project timeline groups

Revision ID: 20260705_0015
Revises: 20260704_0014
Create Date: 2026-07-05 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260705_0015"
down_revision = "20260704_0014"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_timeline_groups")}
    if "is_backlog" not in columns:
        op.add_column(
            "project_timeline_groups",
            sa.Column("is_backlog", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    op.drop_column("project_timeline_groups", "is_backlog")
