"""
Drop the es_index_name column from deduplication_assessment

Revision ID: 0bbd7ec4fdad
Revises: 0d60b739f63e
Create Date: 2026-08-31 04:57:41.624406+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0bbd7ec4fdad'
down_revision: Union[str, None] = '0d60b739f63e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('deduplication_assessment', 'es_index_name')


def downgrade() -> None:
    op.add_column('deduplication_assessment', sa.Column('es_index_name', sa.VARCHAR(), autoincrement=False, nullable=True))
