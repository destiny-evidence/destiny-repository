"""Data models for deduplication scoring."""

from enum import StrEnum, auto
from typing import Self

import destiny_sdk
from pydantic import UUID4, BaseModel, Field

from app.domain.references.models.models import (
    EnhancementType,
    ExternalIdentifierType,
    Reference,
)


class ConfidenceLevel(StrEnum):
    """Confidence level for duplicate detection decisions."""

    HIGH = auto()
    """High confidence: ES score >= 100 or identifier match. Accept immediately."""
    MEDIUM = auto()
    """Medium confidence: ES score >= 50 with Jaccard verification. Accept."""
    LOW = auto()
    """Low confidence: ES score < 50 or failed Jaccard. Reject as duplicate."""


class ReferenceDeduplicationView(BaseModel):
    """
    Lightweight view of a Reference for deduplication scoring.

    This extracts only the fields needed for duplicate detection, avoiding
    the overhead of full Reference model with all relationships.
    """

    id: UUID4 | None = Field(default=None, description="Reference ID")
    title: str | None = Field(default=None, description="Work title")
    authors: list[str] | None = Field(default=None, description="Author names")
    publication_year: int | None = Field(default=None, description="Publication year")
    doi: str | None = Field(default=None, description="DOI identifier")
    openalex_id: str | None = Field(default=None, description="OpenAlex W ID")
    pmid: str | None = Field(default=None, description="PubMed ID")

    @classmethod
    def from_reference(cls, reference: Reference) -> Self:
        """
        Create a deduplication view from a Reference.

        Extracts bibliographic fields from enhancements and identifiers.
        Requires enhancements and identifiers to be preloaded.

        Args:
            reference: The Reference to extract fields from.

        Returns:
            A ReferenceDeduplicationView with extracted fields.

        """
        # Extract bibliographic fields from enhancements
        title: str | None = None
        authors: list[str] | None = None
        publication_year: int | None = None

        if reference.enhancements:
            # Process enhancements by created_at order (latest wins)
            for enhancement in sorted(
                reference.enhancements,
                key=lambda e: e.created_at.timestamp() if e.created_at else 0,
            ):
                if (
                    enhancement.content.enhancement_type
                    == EnhancementType.BIBLIOGRAPHIC
                ):
                    title = enhancement.content.title or title
                    publication_year = (
                        enhancement.content.publication_year
                        or (
                            enhancement.content.publication_date.year
                            if enhancement.content.publication_date
                            else None
                        )
                        or publication_year
                    )
                    if enhancement.content.authorship:
                        authors = cls._extract_author_names(
                            enhancement.content.authorship
                        )

        # Extract identifiers
        doi: str | None = None
        openalex_id: str | None = None
        pmid: str | None = None

        if reference.identifiers:
            for linked_id in reference.identifiers:
                id_type = linked_id.identifier.identifier_type
                id_value = str(linked_id.identifier.identifier)
                if id_type == ExternalIdentifierType.DOI:
                    doi = id_value
                elif id_type == ExternalIdentifierType.OPEN_ALEX:
                    openalex_id = id_value
                elif id_type == ExternalIdentifierType.PM_ID:
                    pmid = id_value

        return cls(
            id=reference.id,
            title=title,
            authors=authors,
            publication_year=publication_year,
            doi=doi,
            openalex_id=openalex_id,
            pmid=pmid,
        )

    @staticmethod
    def _extract_author_names(
        authorship: list[destiny_sdk.enhancements.Authorship],
    ) -> list[str]:
        """Extract author display names, ordered by position."""
        return [
            author.display_name
            for author in sorted(
                authorship,
                key=lambda author: (
                    {
                        destiny_sdk.enhancements.AuthorPosition.FIRST: -1,
                        destiny_sdk.enhancements.AuthorPosition.LAST: 1,
                    }.get(author.position, 0),
                    author.display_name,
                ),
            )
        ]


class ScoringResult(BaseModel):
    """Result of scoring a candidate against a source reference."""

    combined_score: float = Field(
        description="Combined score (0.0 to 1.0) for duplicate confidence"
    )
    confidence: ConfidenceLevel = Field(description="Confidence level of the decision")
    es_score: float | None = Field(default=None, description="Elasticsearch BM25 score")
    jaccard_score: float | None = Field(
        default=None, description="Title token Jaccard similarity"
    )
    id_match_type: str | None = Field(
        default=None,
        description="Type of identifier match: 'openalex', 'doi_safe', or None",
    )
