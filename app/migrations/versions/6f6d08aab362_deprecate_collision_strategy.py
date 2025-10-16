"""
deprecate collision_strategy

Revision ID: 6f6d08aab362
Revises: e2b5649fcd0b
Create Date: 2025-10-02 23:27:25.113341+00:00

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6f6d08aab362'
down_revision: Union[str, None] = 'e2b5649fcd0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adds 'deprecated' to the enum and sets it as the default value
    connection = op.get_bind()
    op.execute("ALTER TYPE collision_strategy ADD VALUE IF NOT EXISTS 'deprecated'")
    op.execute("ALTER TYPE collision_strategy ADD VALUE IF NOT EXISTS 'append'")
    connection.commit()
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
