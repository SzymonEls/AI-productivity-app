"""Add project day slots and the daily time target

Revision ID: 20260808_0016
Revises: 20260705_0015
Create Date: 2026-08-09

Autogenerate also wanted to drop ix_project_time_entries_user_ended and
ix_project_time_entries_user_project_started. Those indexes are created by
migration 20260520_0009, but were not declared on the model when this migration
was written, so dropping them here would quietly remove indexes the application
relies on. Both drops were deleted from this migration on purpose. (The model
declares them now, which is what stopped autogenerate proposing the drops.)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260808_0016'
down_revision = '20260705_0015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'project_day_slots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('slot_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.String(length=1), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'slot_date', 'slot', name='uq_project_day_slot'),
    )
    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        batch_op.create_index('ix_project_day_slots_project_date', ['project_id', 'slot_date'], unique=False)
        batch_op.create_index('ix_project_day_slots_user_date', ['user_id', 'slot_date'], unique=False)

    # Nullable, so no server_default is needed: existing rows simply have no target.
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('daily_target_minutes', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('daily_target_minutes')

    with op.batch_alter_table('project_day_slots', schema=None) as batch_op:
        batch_op.drop_index('ix_project_day_slots_user_date')
        batch_op.drop_index('ix_project_day_slots_project_date')

    op.drop_table('project_day_slots')
