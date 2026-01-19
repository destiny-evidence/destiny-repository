"""
Remove collision_strategy enum type

Revision ID: 02e834e89d85
Revises: 6236e2ffc4f5
Create Date: 2026-01-19 01:36:30.669624+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '02e834e89d85'
down_revision: Union[str, None] = '6236e2ffc4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This type isn't used anywhere, so it can be dropped safely
    op.execute("DROP TYPE IF EXISTS collision_strategy")

def downgrade() -> None:
    op.execute("CREATE TYPE collision_strategy AS ENUM('discard', 'fail', 'overwrite', 'merge_aggressive', 'merge_defensive', 'deprecated', 'append')")
