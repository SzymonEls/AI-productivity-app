"""Preserve time entries when their project is deleted

Revision ID: 20260703_0011
Revises: 20260701_0010
Create Date: 2026-07-03 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260703_0011"
down_revision = "20260701_0010"
branch_labels = None
depends_on = None


def upgrade():
    columns = _columns("project_time_entries")
    if columns is None:
        return

    if "project_title_snapshot" not in columns:
        with op.batch_alter_table("project_time_entries") as batch_op:
            batch_op.add_column(sa.Column("project_title_snapshot", sa.String(length=150), nullable=True))

        op.execute(
            "UPDATE project_time_entries "
            "SET project_title_snapshot = ("
            "SELECT title FROM projects WHERE projects.id = project_time_entries.project_id"
            ") "
            "WHERE project_title_snapshot IS NULL AND project_id IS NOT NULL"
        )

    if not columns.get("project_id", {}).get("nullable", True):
        with op.batch_alter_table("project_time_entries") as batch_op:
            batch_op.alter_column("project_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    columns = _columns("project_time_entries")
    if columns is None:
        return

    if columns.get("project_id", {}).get("nullable", False):
        op.execute(
            "DELETE FROM project_time_entries WHERE project_id IS NULL"
        )
        with op.batch_alter_table("project_time_entries") as batch_op:
            batch_op.alter_column("project_id", existing_type=sa.Integer(), nullable=False)

    if "project_title_snapshot" in columns:
        with op.batch_alter_table("project_time_entries") as batch_op:
            batch_op.drop_column("project_title_snapshot")


def _columns(table_name):
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return None
    return {column["name"]: column for column in inspector.get_columns(table_name)}
