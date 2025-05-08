"""
rename enhancement.processor_version to enhancement.robot_version

Revision ID: 13677d5ee575
Revises: 8122d8e2dc7d
Create Date: 2025-05-08 03:02:27.086389+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '13677d5ee575'
down_revision: Union[str, None] = '8122d8e2dc7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename processor_version to robot_version
    op.alter_column('enhancement', 'processor_version', new_column_name='robot_version')


def downgrade() -> None:
    # Rename robot_version back to processor_version
    op.alter_column('enhancement', 'robot_version', new_column_name='processor_version')
