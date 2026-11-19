"""
lowercase pending enhancement index

Revision ID: 3031d2ef42c9
Revises: 04af6b0321f6
Create Date: 2026-11-18 01:42:23.511841+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3031d2ef42c9'
down_revision: Union[str, None] = '04af6b0321f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_pending_enhancement_processing', table_name='pending_enhancement', postgresql_where=sa.text("status = 'PROCESSING'"))
    op.create_index('ix_pending_enhancement_processing', 'pending_enhancement', ['status'], unique=False, postgresql_where=sa.text("status = 'processing'"))


def downgrade() -> None:
    op.drop_index('ix_pending_enhancement_processing', table_name='pending_enhancement', postgresql_where=sa.text("status = 'processing'"))
    op.create_index('ix_pending_enhancement_processing', 'pending_enhancement', ['status'], unique=False, postgresql_where=sa.text("status = 'PROCESSING'"))
