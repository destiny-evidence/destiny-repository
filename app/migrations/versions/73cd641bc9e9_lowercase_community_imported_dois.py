"""
lowercase community-imported dois

Revision ID: 73cd641bc9e9
Revises: 068f01d7c1f8
Create Date: 2026-10-22 23:40:55.693535+00:00

"""
from collections.abc import Sequence
from typing import Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '73cd641bc9e9'
down_revision: Union[str, None] = '068f01d7c1f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # OpenAlex and pik-solr imports already store DOIs lowercase. Scoping by the
    # other imports' references limits the scan size.
    op.execute(
        """
        UPDATE external_identifier
        SET identifier = lower(identifier)
        WHERE identifier_type = 'doi'
          AND identifier <> lower(identifier)
          AND reference_id = ANY(ARRAY(
            SELECT result.reference_id
            FROM import_result AS result
            JOIN import_batch AS batch ON batch.id = result.import_batch_id
            JOIN import_record AS record ON record.id = batch.import_record_id
            WHERE record.source_name NOT IN ('openalex', 'pik-solr')
              AND result.reference_id IS NOT NULL
          ))
        """
    )


def downgrade() -> None:
    # Lowercasing is lossy
    pass
