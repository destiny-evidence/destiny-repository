"""
Remove import result status enum type

Revision ID: 402a31ad663e
Revises: 15a866774b9e
Create Date: 2025-12-04 02:04:05.748840+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '402a31ad663e'
down_revision: Union[str, None] = '15a866774b9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('import_result', 'status', type_=sa.String(), existing_nullable=False)
    op.execute("DROP TYPE IF EXISTS import_result_status")


def downgrade() -> None:
    # Not safely downgradable. We can create the enum type, but can't
    # apply it to the pending_enhancement table without triggering the problem
    # we're trying to avoid. See also https://github.com/destiny-evidence/destiny-repository/pull/343#discussion_r2458931314
    pass
