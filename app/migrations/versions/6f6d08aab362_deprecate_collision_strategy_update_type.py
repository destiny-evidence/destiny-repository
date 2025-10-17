"""
deprecate collision_strategy

Revision ID: 6f6d08aab362
Revises: e2b5649fcd0b
Create Date: 2025-10-02 23:27:25.113341+00:00

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6f6d08aab362'
down_revision: Union[str, None] = 'e2b5649fcd0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adds 'deprecated' to the enum
    op.execute("ALTER TYPE collision_strategy ADD VALUE IF NOT EXISTS 'deprecated'")
    op.execute("ALTER TYPE collision_strategy ADD VALUE IF NOT EXISTS 'append'")
    # ### end Alembic commands ###


def downgrade() -> None:
    ### end Alembic commands ###
    pass
