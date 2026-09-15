"""Add subscribed iCal feeds

Revision ID: 20260915_0023
Revises: 20260915_0022
Create Date: 2026-09-15

Not the `calendar_subscriptions` table that migration 20260704_0013 dropped:
that one published this app's plan as a calendar, this one reads someone else's.
The cached body lives on the row so a feed that stops answering keeps showing
what it last said.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260915_0023'
down_revision = '20260915_0022'
branch_labels = None
depends_on = None


def upgrade():
    if _has_table('calendar_feeds'):
        return

    op.create_table(
        'calendar_feeds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('url', sa.String(length=2000), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('cached_ics', sa.Text(), nullable=False, server_default=''),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('calendar_feeds', schema=None) as batch_op:
        batch_op.create_index('ix_calendar_feeds_user', ['user_id'], unique=False)


def downgrade():
    if not _has_table('calendar_feeds'):
        return

    with op.batch_alter_table('calendar_feeds', schema=None) as batch_op:
        batch_op.drop_index('ix_calendar_feeds_user')

    op.drop_table('calendar_feeds')


def _has_table(table_name):
    return table_name in sa.inspect(op.get_bind()).get_table_names()
