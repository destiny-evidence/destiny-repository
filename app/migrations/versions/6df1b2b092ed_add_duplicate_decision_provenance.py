"""Add duplicate decision authority and trigger.

Revision ID: 6df1b2b092ed
Revises: 9b2f1c4d7e83
Create Date: 2026-08-06 00:00:00.000000+00:00

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "6df1b2b092ed"
down_revision: Union[str, None] = "9b2f1c4d7e83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MANUAL_EEF_DECISIONS = """
    detail IS NULL
    AND duplicate_determination IN ('canonical', 'duplicate')
    AND reference_id IN (
        SELECT DISTINCT result.reference_id
        FROM import_result AS result
        JOIN import_batch AS batch ON batch.id = result.import_batch_id
        JOIN import_record AS record ON record.id = batch.import_record_id
        WHERE record.source_name LIKE 'eef-eppi-review-export%'
          AND result.reference_id IS NOT NULL
    )
"""


def upgrade() -> None:
    op.add_column(
        "reference_duplicate_decision",
        sa.Column(
            "decision_authority",
            sa.String(),
            nullable=False,
            server_default="unclassified",
        ),
    )
    op.add_column(
        "reference_duplicate_decision",
        sa.Column(
            "decision_trigger",
            sa.String(),
            nullable=False,
            server_default="unclassified",
        ),
    )

    connection = op.get_bind()
    # Production audit on 2026-08-06 found 1,664 current manual decisions, all
    # linked to EEF imports. Re-derive the population at deployment for #752/#771.
    expected = connection.execute(
        sa.text(
            "SELECT count(*) FROM reference_duplicate_decision WHERE "
            + _MANUAL_EEF_DECISIONS
        )
    ).scalar_one()
    result = connection.execute(
        sa.text(
            "UPDATE reference_duplicate_decision "
            "SET decision_authority = 'person', decision_trigger = 'migration' "
            "WHERE "
            + _MANUAL_EEF_DECISIONS
        )
    )
    if result.rowcount != expected:
        msg = f"Expected to classify {expected} manual decisions; updated {result.rowcount}."
        raise RuntimeError(msg)

    # Server defaults stay: deploy and migrate are unordered jobs, so an old
    # revision keeps serving and inserting without these columns.


def downgrade() -> None:
    op.drop_column("reference_duplicate_decision", "decision_trigger")
    op.drop_column("reference_duplicate_decision", "decision_authority")
