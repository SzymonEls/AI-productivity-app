"""Add the two MCP credentials: a bearer token and a secret in the URL

Revision ID: 20261126_0040
Revises: 20261122_0039
Create Date: 2026-11-26

Both start out NULL, which means switched off: Claude reaches nothing until the
account page turns one on. Unique indexes, because each value alone names the
account it belongs to; SQLite lets any number of rows hold NULL in them.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261126_0040'
down_revision = '20261122_0039'
branch_labels = None
depends_on = None


COLUMNS = ('mcp_token', 'mcp_url_secret')


def upgrade():
    existing = _column_names('users')
    with op.batch_alter_table('users', schema=None) as batch_op:
        for name in COLUMNS:
            if name not in existing:
                batch_op.add_column(sa.Column(name, sa.String(length=64), nullable=True))
                batch_op.create_index(f'ix_users_{name}', [name], unique=True)


def downgrade():
    existing = _column_names('users')
    with op.batch_alter_table('users', schema=None) as batch_op:
        for name in COLUMNS:
            if name in existing:
                batch_op.drop_index(f'ix_users_{name}')
                batch_op.drop_column(name)


def _column_names(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
