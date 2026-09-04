"""Add the failed sign-in table

Revision ID: 20260827_0020
Revises: 20260823_0019
Create Date: 2026-08-27

Failed sign-ins were counted in the worker process, which meant one budget per
Gunicorn worker rather than one for the application. The table is the only
store every worker already shares.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260827_0020'
down_revision = '20260823_0019'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'login_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=255), nullable=False),
        sa.Column('failed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('login_attempts', schema=None) as batch_op:
        batch_op.create_index(
            'ix_login_attempts_scope_failed_at', ['scope', 'failed_at'], unique=False
        )


def downgrade():
    with op.batch_alter_table('login_attempts', schema=None) as batch_op:
        batch_op.drop_index('ix_login_attempts_scope_failed_at')
    op.drop_table('login_attempts')
