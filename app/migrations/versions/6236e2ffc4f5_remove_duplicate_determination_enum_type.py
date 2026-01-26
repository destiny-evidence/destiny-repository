"""
Remove duplicate determination enum type

Revision ID: 6236e2ffc4f5
Revises: 7bb7cd39e022
Create Date: 2026-01-19 01:09:17.233507+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6236e2ffc4f5'
down_revision: Union[str, None] = '7bb7cd39e022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'reference_duplicate_decision',
        'duplicate_determination',
        type_=sa.String(),
        existing_nullable=False
    )
    op.execute("DROP TYPE IF EXISTS duplicate_determination")

def downgrade() -> None:
    # Not safely downgradable. We can create the enum type, but can't
    # apply it to the table without triggering the problem
    # we're trying to avoid. See also https://github.com/destiny-evidence/destiny-repository/pull/343#discussion_r2458931314
    pass
