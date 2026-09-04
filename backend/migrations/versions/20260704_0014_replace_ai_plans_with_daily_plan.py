"""Replace ai_plans with a single-slot daily_plans table

Revision ID: 20260704_0014
Revises: 20260704_0013
Create Date: 2026-07-04 14:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260704_0014"
down_revision = "20260704_0013"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("ai_plans"):
        op.drop_table("ai_plans")

    if not sa.inspect(op.get_bind()).has_table("daily_plans"):
        op.create_table(
            "daily_plans",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("daily_plans"):
        op.drop_table("daily_plans")

    if not sa.inspect(op.get_bind()).has_table("ai_plans"):
        op.create_table(
            "ai_plans",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("plan_type", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("user_prompt", sa.Text(), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=True),
            sa.Column("project_title_snapshot", sa.String(length=150), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("request_payload", sa.Text(), nullable=True),
            sa.Column("response_payload", sa.Text(), nullable=False),
            sa.Column("is_pinned", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
