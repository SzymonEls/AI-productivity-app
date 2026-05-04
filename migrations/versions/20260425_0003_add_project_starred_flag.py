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
    op.add_column(
        "projects",
        sa.Column(
            "is_starred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("projects", "is_starred", server_default=None)


def downgrade():
    op.drop_column("projects", "is_starred")
