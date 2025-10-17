"""
deprecate collision_strategy

Revision ID: 948cfaa5bb9e
Revises: 6f6d08aab362
Create Date: 2025-10-02 23:27:25.113341+00:00

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '948cfaa5bb9e'
down_revision: Union[str, None] = '6f6d08aab362'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sets 'deprecated' as the default value
    op.alter_column(
        'import_batch',
        'collision_strategy',
        existing_type=postgresql.ENUM(
            'discard', 'fail', 'overwrite', 'merge_aggressive', 'merge_defensive', 'append', 'deprecated',
            name='collision_strategy'
        ),
        server_default="deprecated",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # Remove server default
    op.alter_column(
        'import_batch',
        'collision_strategy',
        existing_type=postgresql.ENUM(
            'discard', 'fail', 'overwrite', 'merge_aggressive', 'merge_defensive', 'append', 'deprecated',
            name='collision_strategy'
        ),
        server_default=None,
    )
    # ### end Alembic commands ###
