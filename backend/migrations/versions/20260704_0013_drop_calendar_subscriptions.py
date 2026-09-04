"""Drop calendar subscriptions

Revision ID: 20260704_0013
Revises: 20260704_0012
Create Date: 2026-07-04 13:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260704_0013"
down_revision = "20260704_0012"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("calendar_subscriptions"):
        op.drop_table("calendar_subscriptions")


def downgrade():
    if sa.inspect(op.get_bind()).has_table("calendar_subscriptions"):
        return

    op.create_table(
        "calendar_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("ical_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
