"""
Add PROCESSING status to EnhancementRequestStatus

Revision ID: e28cce22a108
Revises: f80394742e3e
Create Date: 2025-09-04 06:21:33.961408+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e28cce22a108'
down_revision: Union[str, None] = 'f80394742e3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE enhancement_request_status ADD VALUE 'processing'")


def downgrade() -> None:
    # This downgrade assumes that there are no enhancement requests with the status
    # 'processing'. If there are, this migration will fail.
    op.execute("ALTER TYPE enhancement_request_status RENAME TO enhancement_request_status_old")
    op.execute(
        "CREATE TYPE enhancement_request_status AS ENUM('received', 'accepted', 'rejected', 'partial_failed', 'failed', 'importing', 'indexing', 'indexing_failed', 'completed')"
    )
    op.execute(
        (
            "ALTER TABLE enhancement_request ALTER COLUMN request_status TYPE enhancement_request_status USING "
            "request_status::text::enhancement_request_status"
        )
    )
    op.execute("DROP TYPE enhancement_request_status_old")
