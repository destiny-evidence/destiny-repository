"""
add enhancement supersession columns

Revision ID: 69c1a291fb0a
Revises: a1c4f7e29b30
Create Date: 2026-10-05 02:10:55.373811+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '69c1a291fb0a'
down_revision: Union[str, None] = 'a1c4f7e29b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.add_column('enhancement', sa.Column('supersedes', sa.UUID(), nullable=True))
    op.add_column('enhancement', sa.Column('root_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_enhancement_supersedes', 'enhancement', 'enhancement', ['supersedes'], ['id'], postgresql_not_valid=True)
    op.create_check_constraint('ck_enhancement_supersedes_order', 'enhancement', 'id > supersedes OR supersedes = root_id', postgresql_not_valid=True)
    op.create_check_constraint('ck_enhancement_supersedes_root_id', 'enhancement', 'supersedes IS NULL OR root_id <> id', postgresql_not_valid=True)
    op.create_check_constraint('ck_enhancement_root_id_not_null', 'enhancement', 'root_id IS NOT NULL', postgresql_not_valid=True)


def downgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint('ck_enhancement_root_id_not_null', 'enhancement', type_='check')
    op.drop_constraint('ck_enhancement_supersedes_root_id', 'enhancement', type_='check')
    op.drop_constraint('ck_enhancement_supersedes_order', 'enhancement', type_='check')
    op.drop_constraint('fk_enhancement_supersedes', 'enhancement', type_='foreignkey')
    op.drop_column('enhancement', 'root_id')
    op.drop_column('enhancement', 'supersedes')
