"""
lowercase pending enhancement statuses

Revision ID: 5215ff42a003
Revises: 3031d2ef42c9
Create Date: 2026-11-18 02:35:23.113290+00:00

"""
from collections.abc import Sequence
from typing import Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5215ff42a003'
down_revision: Union[str, None] = '3031d2ef42c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE pending_enhancement SET status = 'failed' WHERE status IN ('PENDING', 'PROCESSING')")
    op.execute("UPDATE pending_enhancement SET status = lower(status) WHERE status IN ('COMPLETED', 'FAILED', 'INDEXING_FAILED')")


def downgrade() -> None:
    # Legacy uppercase statuses are not recoverable after upgrade.
    pass
