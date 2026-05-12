"""Add project and timeline item privacy

Revision ID: 20260512_0007
Revises: 20260427_0006
Create Date: 2026-05-12 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260512_0007"
down_revision = "20260427_0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.alter_column("is_private", server_default=None)

    with op.batch_alter_table("project_timeline_items") as batch_op:
        batch_op.add_column(
            sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.alter_column("is_private", server_default=None)


def downgrade():
    with op.batch_alter_table("project_timeline_items") as batch_op:
        batch_op.drop_column("is_private")

    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("is_private")
