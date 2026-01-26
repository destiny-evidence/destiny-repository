"""
Remove the visibility enum

Revision ID: 827292b63821
Revises: 931cd65e804b
Create Date: 2026-01-19 22:35:56.461397+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '827292b63821'
down_revision: Union[str, None] = '931cd65e804b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('reference', 'visibility', type_=sa.String(), existing_nullable=False)
    op.execute("DROP TYPE IF EXISTS visibility")


def downgrade() -> None:
    # Cannot be safely downgraded. We can create the enum type, but can't
    # apply it to the table without triggering the problem
    # we're trying to avoid. See also https://github.com/destiny-evidence/destiny-repository/pull/343#discussion_r2458931314
    pass
