"""
Remove import record status enum type

Revision ID: 75680bf07a66
Revises: 402a31ad663e
Create Date: 2026-01-19 00:18:09.727334+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '75680bf07a66'
down_revision: Union[str, None] = '402a31ad663e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('import_record', 'status', type_=sa.String(), existing_nullable=False)
    op.execute("DROP TYPE IF EXISTS import_record_status")


def downgrade() -> None:
    # Cannot be safely downgraded. We can create the enum type, but can't
    # apply it to the table without triggering the problem
    # we're trying to avoid. See also https://github.com/destiny-evidence/destiny-repository/pull/343#discussion_r2458931314
    pass
