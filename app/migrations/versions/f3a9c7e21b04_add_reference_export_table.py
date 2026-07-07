"""
add reference_export table

Revision ID: f3a9c7e21b04
Revises: bce864c7c06e
Create Date: 2026-07-07 00:00:00.000000+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3a9c7e21b04'
down_revision: Union[str, None] = 'bce864c7c06e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('reference_export',
    sa.Column('reference_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('export_format', sa.String(), server_default='jsonl', nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('result_file', sa.String(), nullable=True),
    sa.Column('n_references', sa.Integer(), nullable=True),
    sa.Column('error', sa.String(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('reference_export')
