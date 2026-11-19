"""
add search export chunks

Revision ID: 2a40c90eb734
Revises: 04af6b0321f6
Create Date: 2026-11-17 00:00:00.000000+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2a40c90eb734'
down_revision: Union[str, None] = '04af6b0321f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reference_export', sa.Column('search_export_id', sa.UUID(), nullable=True))
    op.add_column('reference_export', sa.Column('chunk_index', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_reference_export_search_export_id', 'reference_export', 'search_export', ['search_export_id'], ['id'])
    op.create_unique_constraint('uix_reference_export_chunk', 'reference_export', ['search_export_id', 'chunk_index'])
    op.alter_column('reference_export', 'reference_ids', existing_type=postgresql.ARRAY(sa.UUID()), nullable=True)
    op.drop_column('search_export', 'status')


def downgrade() -> None:
    op.add_column('search_export', sa.Column('status', sa.String(), nullable=True))
    op.execute(
        """
        UPDATE search_export SET status = CASE
            WHEN error IS NOT NULL OR EXISTS (
                SELECT 1 FROM reference_export
                WHERE search_export_id = search_export.id AND status = 'failed'
            ) THEN 'failed'
            WHEN result_file IS NOT NULL THEN 'completed'
            ELSE 'pending'
        END
        """
    )
    op.alter_column('search_export', 'status', nullable=False)
    op.execute("DELETE FROM reference_export WHERE search_export_id IS NOT NULL")
    op.alter_column('reference_export', 'reference_ids', existing_type=postgresql.ARRAY(sa.UUID()), nullable=False)
    op.drop_constraint('uix_reference_export_chunk', 'reference_export', type_='unique')
    op.drop_constraint('fk_reference_export_search_export_id', 'reference_export', type_='foreignkey')
    op.drop_column('reference_export', 'chunk_index')
    op.drop_column('reference_export', 'search_export_id')
