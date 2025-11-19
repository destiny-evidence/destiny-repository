"""
remove enhancement_type enum from postgres

Revision ID: eb47e22ea5af
Revises: 41a6980bb04e
Create Date: 2025-11-19 21:25:51.203209+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'eb47e22ea5af'
down_revision: Union[str, None] = '41a6980bb04e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('enhancement', 'enhancement_type',
               existing_type=postgresql.ENUM('bibliographic', 'abstract', 'annotation', 'location', name='enhancement_type'),
               type_=sa.String(),
               existing_nullable=False)
    op.execute("DROP TYPE IF EXISTS enhancement_type")


def downgrade() -> None:
    # Not safely downgradable. We can create the enum type, but can't
    # apply it to the pending_enhancement table without triggering the problem
    # we're trying to avoid. See also https://github.com/destiny-evidence/destiny-repository/pull/343#discussion_r2458931314
    pass
