"""
rename batch enhancement request table to enhancement request

Revision ID: c4b31f92a4a1
Revises: 3418c332afa8
Create Date: 2025-08-26 04:27:30.332488+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c4b31f92a4a1'
down_revision: Union[str, None] = '3418c332afa8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table('batch_enhancement_request', 'enhancement_request')
    op.execute('ALTER INDEX batch_enhancement_request_pkey RENAME TO enhancement_request_pkey')
    op.execute('ALTER TYPE batch_enhancement_request_status RENAME TO enhancement_request_status')



def downgrade() -> None:
    op.rename_table('enhancement_request', 'batch_enhancement_request')
    op.execute('ALTER INDEX enhancement_request_pkey RENAME TO batch_enhancement_request_pkey')
    op.execute('ALTER TYPE enhancement_request_status RENAME TO batch_enhancement_request_status')
