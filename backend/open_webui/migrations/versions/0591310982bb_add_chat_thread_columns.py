"""add chat thread columns

Revision ID: 0591310982bb
Revises: d4c1a8e37b62
Create Date: 2026-08-27 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0591310982bb'
down_revision: str | None = 'd4c1a8e37b62'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_exists(inspector, index_name, table_name):
    """Check if an index already exists on the given table (works for both SQLite and PostgreSQL)."""
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    chat_cols = {c['name'] for c in inspector.get_columns('chat')}

    if 'parent_chat_id' not in chat_cols:
        op.add_column('chat', sa.Column('parent_chat_id', sa.Text(), nullable=True))
    if 'branch_from_message_id' not in chat_cols:
        op.add_column('chat', sa.Column('branch_from_message_id', sa.Text(), nullable=True))
    if 'root_chat_id' not in chat_cols:
        op.add_column('chat', sa.Column('root_chat_id', sa.Text(), nullable=True))

    inspector.clear_cache()
    if not _index_exists(inspector, 'parent_chat_id_idx', 'chat'):
        op.create_index('parent_chat_id_idx', 'chat', ['parent_chat_id'])
    if not _index_exists(inspector, 'root_chat_id_idx', 'chat'):
        op.create_index('root_chat_id_idx', 'chat', ['root_chat_id'])
    if not _index_exists(inspector, 'parent_chat_branch_message_idx', 'chat'):
        op.create_index('parent_chat_branch_message_idx', 'chat', ['parent_chat_id', 'branch_from_message_id'])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if _index_exists(inspector, 'parent_chat_branch_message_idx', 'chat'):
        op.drop_index('parent_chat_branch_message_idx', table_name='chat')
    if _index_exists(inspector, 'root_chat_id_idx', 'chat'):
        op.drop_index('root_chat_id_idx', table_name='chat')
    if _index_exists(inspector, 'parent_chat_id_idx', 'chat'):
        op.drop_index('parent_chat_id_idx', table_name='chat')

    inspector.clear_cache()
    chat_cols = {c['name'] for c in inspector.get_columns('chat')}
    with op.batch_alter_table('chat') as batch_op:
        if 'root_chat_id' in chat_cols:
            batch_op.drop_column('root_chat_id')
        if 'branch_from_message_id' in chat_cols:
            batch_op.drop_column('branch_from_message_id')
        if 'parent_chat_id' in chat_cols:
            batch_op.drop_column('parent_chat_id')
