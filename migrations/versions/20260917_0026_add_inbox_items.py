"""Add the inbox of uncategorised captured thoughts

Revision ID: 20260917_0026
Revises: 20260917_0025
Create Date: 2026-09-17

A table of its own rather than a column anywhere: an inbox item is defined by
not belonging to a project yet, so there is nothing to hang it off. It holds
only the text - filing one appends it to the project's thoughts and deletes the
row, so nothing here outlives the choice.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260917_0026'
down_revision = '20260917_0025'
branch_labels = None
depends_on = None


def upgrade():
    if _has_table('inbox_items'):
        return

    op.create_table(
        'inbox_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.String(length=2000), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('inbox_items', schema=None) as batch_op:
        batch_op.create_index('ix_inbox_items_user', ['user_id'], unique=False)


def downgrade():
    if not _has_table('inbox_items'):
        return

    with op.batch_alter_table('inbox_items', schema=None) as batch_op:
        batch_op.drop_index('ix_inbox_items_user')

    op.drop_table('inbox_items')


def _has_table(table_name):
    return table_name in sa.inspect(op.get_bind()).get_table_names()
