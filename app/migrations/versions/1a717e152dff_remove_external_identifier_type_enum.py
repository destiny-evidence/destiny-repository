"""
Remove external identifier type enum

Revision ID: 1a717e152dff
Revises: eb47e22ea5af
Create Date: 2025-11-19 23:49:04.821842+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1a717e152dff'
down_revision: Union[str, None] = 'eb47e22ea5af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # We have to drop the indices before altering the column or we get operand failures on the where conditions
    # WHERE (identifier_type <> 'other'::public.external_identifier_type);
    # The right side of the above doesn't update when changing the column type, resulting in a
    # character varying <> external_identifier_type comparison which has no valid operator.

    op.drop_index('ix_external_identifier_type_other', table_name='external_identifier', postgresql_where=sa.text("identifier_type = 'other'"))
    op.drop_index('ix_external_identifier_type', table_name='external_identifier', postgresql_where=sa.text("identifier_type != 'other'"))

    op.alter_column('external_identifier', 'identifier_type', type_=sa.String(), existing_nullable=False)
    op.execute("DROP TYPE IF EXISTS external_identifier_type")

    op.create_index('ix_external_identifier_type', 'external_identifier', ['identifier_type', 'identifier'], unique=False, postgresql_where=sa.text("identifier_type != 'other'"))
    op.create_index('ix_external_identifier_type_other', 'external_identifier', ['identifier_type', 'other_identifier_name', 'identifier'], unique=False, postgresql_where=sa.text("identifier_type = 'other'"))



def downgrade() -> None:
    # Not safely downgradable. We can create the enum type, but can't
    # apply it to the pending_enhancement table without triggering the problem
    # we're trying to avoid. See also https://github.com/destiny-evidence/destiny-repository/pull/343#discussion_r2458931314
    pass
