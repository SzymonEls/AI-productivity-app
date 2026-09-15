"""Add the per-day note list

Revision ID: 20260915_0022
Revises: 20260912_0021
Create Date: 2026-09-15

A new table rather than a column on project_day_slots: a note belongs to the
day, not to one of its three blocks, and a day takes as many notes as get
written.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260915_0022'
down_revision = '20260912_0021'
branch_labels = None
depends_on = None


def upgrade():
    if _has_table('day_notes'):
        return

    op.create_table(
        'day_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('note_date', sa.Date(), nullable=False),
        sa.Column('body', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('day_notes', schema=None) as batch_op:
        batch_op.create_index('ix_day_notes_user_date', ['user_id', 'note_date'], unique=False)


def downgrade():
    if not _has_table('day_notes'):
        return

    with op.batch_alter_table('day_notes', schema=None) as batch_op:
        batch_op.drop_index('ix_day_notes_user_date')

    op.drop_table('day_notes')


def _has_table(table_name):
    return table_name in sa.inspect(op.get_bind()).get_table_names()
