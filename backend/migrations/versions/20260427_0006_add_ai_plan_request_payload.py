"""Add AI request payload history

Revision ID: 20260427_0006
Revises: 20260427_0005
Create Date: 2026-04-27 23:30:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260427_0006"
down_revision = "20260427_0005"
branch_labels = None
depends_on = None


def upgrade():
    if _has_column("ai_plans", "request_payload"):
        return

    with op.batch_alter_table("ai_plans") as batch_op:
        batch_op.add_column(sa.Column("request_payload", sa.Text(), nullable=True))


def downgrade():
    if _has_column("ai_plans", "request_payload"):
        with op.batch_alter_table("ai_plans") as batch_op:
            batch_op.drop_column("request_payload")


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
