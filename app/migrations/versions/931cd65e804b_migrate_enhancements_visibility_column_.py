"""
Migrate enhancements visibility column from enum to string

Revision ID: 931cd65e804b
Revises: 02e834e89d85
Create Date: 2026-01-19 20:47:12.371533+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '931cd65e804b'
down_revision: Union[str, None] = '02e834e89d85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'enhancement',
        'visibility',
        type_=sa.String(),
        existing_nullable=False
    )

def downgrade() -> None:
    op.alter_column(
        'enhancement',
        'visibility',
        type_=postgresql.ENUM('public', 'restricted', 'hidden', name='visibility', create_type=False),
        postgresql_using='visibility::visibility',
        existing_nullable=False
    )
