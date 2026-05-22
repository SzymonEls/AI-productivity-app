"""Add project time entries

Revision ID: 20260520_0009
Revises: 20260512_0008
Create Date: 2026-05-20 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260520_0009"
down_revision = "20260512_0008"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("project_time_entries"):
        return

    op.create_table(
        "project_time_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_time_entries_user_project_started",
        "project_time_entries",
        ["user_id", "project_id", "started_at"],
    )
    op.create_index(
        "ix_project_time_entries_user_ended",
        "project_time_entries",
        ["user_id", "ended_at"],
    )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("project_time_entries"):
        return

    op.drop_index("ix_project_time_entries_user_ended", table_name="project_time_entries")
    op.drop_index("ix_project_time_entries_user_project_started", table_name="project_time_entries")
    op.drop_table("project_time_entries")
