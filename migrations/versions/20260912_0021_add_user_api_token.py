"""Add the per-user API token

Revision ID: 20260912_0021
Revises: 20260827_0020
Create Date: 2026-09-12

The token authenticates the menu bar app against /api/v1. Existing rows each
get their own random value instead of sharing the server_default, so no two
accounts start out holding the same credential.
"""
import secrets

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260912_0021'
down_revision = '20260827_0020'
branch_labels = None
depends_on = None


users_table = sa.table(
    'users',
    sa.column('id', sa.Integer),
    sa.column('api_token', sa.String),
)


def upgrade():
    if _has_column('users', 'api_token'):
        return

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('api_token', sa.String(length=64), nullable=False, server_default='')
        )

    connection = op.get_bind()
    for row in connection.execute(sa.select(users_table.c.id)).fetchall():
        connection.execute(
            users_table.update()
            .where(users_table.c.id == row.id)
            .values(api_token=secrets.token_urlsafe(32))
        )


def downgrade():
    if _has_column('users', 'api_token'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('api_token')


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
