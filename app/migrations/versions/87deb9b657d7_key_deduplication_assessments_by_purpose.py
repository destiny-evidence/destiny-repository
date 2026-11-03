"""
Key deduplication assessments by idempotency key and purpose

Revision ID: 87deb9b657d7
Revises: 73cd641bc9e9
Create Date: 2026-11-03 10:55:00.000000+00:00

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '87deb9b657d7'
down_revision: Union[str, None] = '73cd641bc9e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('uq_deduplication_assessment_idempotency_key', table_name='deduplication_assessment')
    op.create_index('uq_deduplication_assessment_idempotency_key_purpose', 'deduplication_assessment', ['idempotency_key', 'purpose'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_deduplication_assessment_idempotency_key_purpose', table_name='deduplication_assessment')
    op.create_index('uq_deduplication_assessment_idempotency_key', 'deduplication_assessment', ['idempotency_key'], unique=True)
