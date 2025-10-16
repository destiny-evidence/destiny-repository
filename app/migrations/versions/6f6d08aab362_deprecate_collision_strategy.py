"""
deprecate collision_strategy

Revision ID: 6f6d08aab362
Revises: e2b5649fcd0b
Create Date: 2025-10-02 23:27:25.113341+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6f6d08aab362'
down_revision: Union[str, None] = 'e2b5649fcd0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deprecate collision_strategy by making it nullable and defaulting to NULL, preserving data
    op.alter_column(
        'import_batch',
        'collision_strategy',
        nullable=True,
        existing_type=postgresql.ENUM(
            'discard', 'fail', 'overwrite', 'merge_aggressive', 'merge_defensive', 'append',
            name='collision_strategy'
        ),
        server_default=None
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # Restore NOT NULL constraint on collision_strategy
    op.alter_column(
        'import_batch',
        'collision_strategy',
        nullable=False,
        existing_type=postgresql.ENUM(
            'discard', 'fail', 'overwrite', 'merge_aggressive', 'merge_defensive', 'append',
            name='collision_strategy'
        )
    )
    # ### end Alembic commands ###
