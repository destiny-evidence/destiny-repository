"""
add partial unique index on pending enhancement (request, reference)

Revision ID: 9b2f1c4d7e83
Revises: 73a049948581
Create Date: 2026-07-27 03:00:00.000000+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9b2f1c4d7e83'
down_revision: Union[str, None] = '73a049948581'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = 'uq_pending_enhancement_request_reference_original'


def upgrade() -> None:
    duplicate_groups = op.get_bind().execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT 1
                FROM pending_enhancement
                WHERE retry_of IS NULL AND enhancement_request_id IS NOT NULL
                GROUP BY enhancement_request_id, reference_id
                HAVING count(*) > 1
            ) duplicates
            """
        )
    ).scalar_one()
    if duplicate_groups:
        msg = (
            f"Cannot create {_INDEX_NAME}: {duplicate_groups} "
            "(enhancement_request_id, reference_id) group(s) already have "
            "multiple original pending enhancements."
        )
        raise RuntimeError(msg)

    op.create_index(
        _INDEX_NAME,
        'pending_enhancement',
        ['enhancement_request_id', 'reference_id'],
        unique=True,
        postgresql_where=sa.text('retry_of IS NULL'),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name='pending_enhancement')
