"""
link duplicate decisions to deduplication assessments

Revision ID: a8f3c2d17e45
Revises: 73cd641bc9e9
Create Date: 2026-10-29 01:00:00.000000+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a8f3c2d17e45'
down_revision: Union[str, None] = '73cd641bc9e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.add_column('reference_duplicate_decision', sa.Column('deduplication_assessment_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_reference_duplicate_decision_deduplication_assessment_id', 'reference_duplicate_decision', 'deduplication_assessment', ['deduplication_assessment_id'], ['id'], postgresql_not_valid=True)
    with op.get_context().autocommit_block():
        # A concurrent build waits on open transactions; timing out would leave an invalid index.
        op.execute("SET lock_timeout = 0")
        op.create_index('ix_reference_duplicate_decision_deduplication_assessment_id', 'reference_duplicate_decision', ['deduplication_assessment_id'], unique=False, postgresql_concurrently=True)
        op.execute('ALTER TABLE reference_duplicate_decision VALIDATE CONSTRAINT fk_reference_duplicate_decision_deduplication_assessment_id')


def downgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint('fk_reference_duplicate_decision_deduplication_assessment_id', 'reference_duplicate_decision', type_='foreignkey')
    op.drop_index('ix_reference_duplicate_decision_deduplication_assessment_id', table_name='reference_duplicate_decision')
    op.drop_column('reference_duplicate_decision', 'deduplication_assessment_id')
