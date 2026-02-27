"""Models for duplicate decisions."""

from enum import StrEnum, auto
from typing import Self

from pydantic import BaseModel, Field, model_validator

from destiny_sdk.core import UUID


class ManualDuplicateDetermination(StrEnum):
    """The determination of whether a reference is a duplicate."""

    DUPLICATE = auto()
    """[TERMINAL] The reference is a duplicate of another reference."""
    CANONICAL = auto()
    """[TERMINAL] The reference is not a duplicate of another reference."""


class MakeDuplicateDecision(BaseModel):
    """Model for making a duplicate decision."""

    reference_id: UUID = Field(
        description="The ID of the reference this decision applies to."
    )
    duplicate_determination: ManualDuplicateDetermination = Field(
        description="The duplicate status of the reference."
    )
    canonical_reference_id: UUID | None = Field(
        default=None,
        description="The ID of the canonical reference this reference duplicates.",
    )
    detail: str | None = Field(
        default=None,
        description="Optional additional detail about the decision.",
    )

    @model_validator(mode="after")
    def check_canonical_reference_id_populated_iff_duplicate(self) -> Self:
        """Assert that canonical must exist if and only if decision is duplicate."""
        if (self.canonical_reference_id is not None) != (
            self.duplicate_determination == ManualDuplicateDetermination.DUPLICATE
        ):
            msg = (
                "canonical_reference_id must be populated if and only if "
                "duplicate_determination is DUPLICATE."
            )
            raise ValueError(msg)

        return self
