"""Models for duplicate decisions."""

from enum import StrEnum, auto
from typing import Self

from pydantic import BaseModel, Field, model_validator

from destiny_sdk.core import UUID


class ManualDuplicateDetermination(StrEnum):
    """The determination of whether a reference is a duplicate."""

    DUPLICATE = auto()
    """The reference is a duplicate of another reference."""
    CANONICAL = auto()
    """The reference is not a duplicate of another reference."""


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


class ManualDuplicateDeterminationResult(StrEnum):
    """The possible outcomes of applying a manual duplicate decision."""

    DUPLICATE = auto()
    """The reference was marked as a duplicate of a canonical reference."""
    CANONICAL = auto()
    """The reference was marked as canonical (not a duplicate)."""
    DECOUPLED = auto()
    """The decision was reclassified and needs further attention."""


class MakeDuplicateDecisionResult(BaseModel):
    """Result of applying a duplicate decision."""

    id: UUID = Field(description="The ID of the duplicate decision record.")
    reference_id: UUID = Field(
        description="The ID of the reference this decision applies to."
    )
    outcome: ManualDuplicateDeterminationResult = Field(
        description="The resolved outcome. "
    )
    canonical_reference_id: UUID | None = Field(
        default=None,
        description="The ID of the canonical reference, if applicable.",
    )
    active_decision: bool = Field(
        description="Whether this decision is the active decision for the reference.",
    )
    detail: str | None = Field(
        default=None,
        description="Additional detail about the decision.",
    )
