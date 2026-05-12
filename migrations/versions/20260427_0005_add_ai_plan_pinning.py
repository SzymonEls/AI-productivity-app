"""Add AI plan pinning

Revision ID: 20260427_0005
Revises: 20260425_0004
Create Date: 2026-04-27 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260427_0005"
down_revision = "20260425_0004"
branch_labels = None
depends_on = None


def upgrade():
    if _has_column("ai_plans", "is_pinned"):
        return

    with op.batch_alter_table("ai_plans") as batch_op:
        batch_op.add_column(
            sa.Column("is_pinned", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade():
    if _has_column("ai_plans", "is_pinned"):
        with op.batch_alter_table("ai_plans") as batch_op:
            batch_op.drop_column("is_pinned")


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
