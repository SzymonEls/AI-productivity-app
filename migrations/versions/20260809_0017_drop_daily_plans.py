"""Drop the daily plan module

Revision ID: 20260809_0017
Revises: 20260808_0016
Create Date: 2026-08-09

The manual daily-plan builder (the app/ai/ blueprint) was removed, so the table
it wrote to goes with it.

This deletes data. downgrade() recreates the table, but empty - there is nowhere
to restore the plans from. Back up before upgrading a live instance:

    sqlite3 app/instance/app.db ".dump daily_plans" > daily-plans-backup.sql

has_table() is checked both ways so the migration is safe on a database that
never had the table (or already lost it), mirroring 20260704_0014.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260809_0017'
down_revision = '20260808_0016'
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("daily_plans"):
        op.drop_table("daily_plans")


def downgrade():
    if sa.inspect(op.get_bind()).has_table("daily_plans"):
        return

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
