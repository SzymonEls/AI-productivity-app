"""Add the daily mood rating

Revision ID: 20261027_0034
Revises: 20261017_0033
Create Date: 2026-10-27

A table of its own: one 1-5 score per user and day, unique on the pair so
rating a day again rewrites it. Nothing to backfill - no day has been rated.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261027_0034'
down_revision = '20261017_0033'
branch_labels = None
depends_on = None


def upgrade():
    if _has_table('mood_ratings'):
        return

    op.create_table(
        'mood_ratings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('rating_date', sa.Date(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'rating_date', name='uq_mood_rating_day'),
    )


def downgrade():
    if not _has_table('mood_ratings'):
        return

    op.drop_table('mood_ratings')


def _has_table(table_name):
    return table_name in sa.inspect(op.get_bind()).get_table_names()
