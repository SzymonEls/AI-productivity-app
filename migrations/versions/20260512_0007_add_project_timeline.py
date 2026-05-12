"""Add project timeline tables

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
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("project_timeline_groups"):
        op.create_table(
            "project_timeline_groups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=150), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not inspector.has_table("project_timeline_items"):
        op.create_table(
            "project_timeline_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("item_type", sa.String(length=20), nullable=False),
            sa.Column("title", sa.String(length=180), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["project_timeline_groups.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    op.drop_table("project_timeline_items")
    op.drop_table("project_timeline_groups")
