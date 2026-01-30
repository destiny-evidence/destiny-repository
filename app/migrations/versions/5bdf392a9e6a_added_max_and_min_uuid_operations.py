"""
Added max and min uuid operations

Revision ID: 5bdf392a9e6a
Revises: 827292b63821
Create Date: 2026-01-29 08:35:38.541608+00:00

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5bdf392a9e6a'
down_revision: Union[str, None] = '827292b63821'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgresql doesn't ship with min/max aggregate functions for uuid types by default,
    # so we need to create our own.
    # Fortunately, postgresql does ship with comparison operators for uuid types...

    op.execute("""
        CREATE OR REPLACE FUNCTION uuid_smaller(uuid, uuid) RETURNS uuid AS $$
            SELECT CASE
                WHEN $1 IS NULL THEN $2
                WHEN $2 IS NULL THEN $1
                WHEN $1 < $2 THEN $1
                ELSE $2
            END;
        $$ LANGUAGE SQL IMMUTABLE PARALLEL SAFE
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION uuid_larger(uuid, uuid) RETURNS uuid AS $$
            SELECT CASE
                WHEN $1 IS NULL THEN $2
                WHEN $2 IS NULL THEN $1
                WHEN $1 > $2 THEN $1
                ELSE $2
            END;
        $$ LANGUAGE SQL IMMUTABLE PARALLEL SAFE
    """)
    op.execute("""
        CREATE AGGREGATE min(uuid) (
            SFUNC = uuid_smaller,
            STYPE = uuid,
            COMBINEFUNC = uuid_smaller,
            PARALLEL = SAFE,
            SORTOP = <
        )
    """)
    op.execute("""
        CREATE AGGREGATE max(uuid) (
            SFUNC = uuid_larger,
            STYPE = uuid,
            COMBINEFUNC = uuid_larger,
            PARALLEL = SAFE,
            SORTOP = >
        )
    """)


def downgrade() -> None:
    op.execute("DROP AGGREGATE IF EXISTS min(uuid)")
    op.execute("DROP AGGREGATE IF EXISTS max(uuid)")
    op.execute("DROP FUNCTION IF EXISTS uuid_smaller(uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS uuid_larger(uuid, uuid)")
