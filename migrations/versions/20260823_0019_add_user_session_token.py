"""Add the per-user session token

Revision ID: 20260823_0019
Revises: 20260809_0018
Create Date: 2026-08-23

The token is half of what the session and "remember me" cookies carry, so
changing a password can invalidate the cookies already issued. Existing rows
each get their own random value rather than sharing the server_default, so
that the column carries a real secret from the moment it exists.
"""
import secrets

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260823_0019'
down_revision = '20260809_0018'
branch_labels = None
depends_on = None


users_table = sa.table(
    'users',
    sa.column('id', sa.Integer),
    sa.column('session_token', sa.String),
)


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('session_token', sa.String(length=64), nullable=False, server_default='')
        )

    connection = op.get_bind()
    for row in connection.execute(sa.select(users_table.c.id)).fetchall():
        connection.execute(
            users_table.update()
            .where(users_table.c.id == row.id)
            .values(session_token=secrets.token_hex(32))
        )


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('session_token')
