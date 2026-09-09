"""drop pending_enhancement.reference_id foreign key

Revision ID: a1c4f7e29b30
Revises: 0bbd7ec4fdad
Create Date: 2026-09-08

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1c4f7e29b30"
down_revision: str | None = "0bbd7ec4fdad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "pending_enhancement_reference_id_fkey"


def upgrade() -> None:
    """Drop the reference_id foreign key."""
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint(
        CONSTRAINT_NAME,
        "pending_enhancement",
        type_="foreignkey",
    )


def downgrade() -> None:
    """Restore the foreign key without revalidating existing rows.

    NOTE: this'll be slow!!!
    """
    op.execute(
        f"ALTER TABLE pending_enhancement "
        f"ADD CONSTRAINT {CONSTRAINT_NAME} "
        f"FOREIGN KEY (reference_id) REFERENCES reference (id) NOT VALID"
    )
