"""Projection functions for reference domain data."""

import destiny_sdk

from app.core.exceptions import ProjectionError
from app.domain.base import GenericProjection
from app.domain.references.models.models import (
    CandidateDuplicateSearchFields,
    EnhancementType,
    Reference,
)


class CandidateDuplicateSearchFieldsProjection(
    GenericProjection[CandidateDuplicateSearchFields]
):
    """Projection functions for candidate selection used in duplicate detection."""

    @classmethod
    def get_from_reference(
        cls,
        reference: Reference,
    ) -> CandidateDuplicateSearchFields:
        """Get the candidate duplicate search fields from a reference."""
        try:
            title, publication_year = None, None
            authorship: list[destiny_sdk.enhancements.Authorship] = []
            # NB at present we have no way of discriminating between multiple
            # bibliographic enhancements, nor are they ordered. This takes a
            # random one, preferencing the canonical reference itself,
            # (but hydrates in the case of one bibliographic enhancement
            # missing a field while the other has it present).
            for enhancement in sorted(
                reference.enhancements or [],
                # This preferences the canonical reference's enhancements
                # over those of its duplicates.
                key=lambda e: e.reference_id == reference.id,
                reverse=True,
            ):
                if (
                    enhancement.content.enhancement_type
                    == EnhancementType.BIBLIOGRAPHIC
                ):
                    # Hydrate if exists on enhancement, otherwise use prior value
                    title = enhancement.content.title or title
                    authorship = enhancement.content.authorship or authorship
                    publication_year = (
                        enhancement.content.publication_year
                        or (
                            enhancement.content.publication_date.year
                            if enhancement.content.publication_date
                            else None
                        )
                        or publication_year
                    )

            # Author normalization:
            # Maintain first and last author, sort middle authors by name
            authorship = sorted(
                authorship,
                key=lambda author: (
                    {
                        destiny_sdk.enhancements.AuthorPosition.FIRST: -1,
                        destiny_sdk.enhancements.AuthorPosition.LAST: 1,
                    }.get(author.position, 0),
                    author.display_name.strip(),
                ),
            )

            if title:
                title = title.strip()

        except Exception as exc:
            msg = "Failed to project CandidateDuplicateSearchFields from Reference"
            raise ProjectionError(msg) from exc

        return CandidateDuplicateSearchFields(
            title=title,
            authors=[author.display_name.strip() for author in authorship],
            publication_year=publication_year,
        )


class DeduplicatedReferenceProjection(GenericProjection[Reference]):
    """
    Projection functions for deduplicating canonical references.

    A deduplicated reference contains all the enhancements and identifiers of its
    duplicates, and is flattened to remove its duplicates. This makes it compatible
    with a SDK reference.
    """

    @classmethod
    def get_from_reference(cls, reference: Reference) -> Reference:
        """Get the deduplicated reference from a reference."""
        if reference.duplicate_references is None:
            msg = "Reference must have duplicates preloaded to be deduplicated."
            raise ProjectionError(msg)

        deduplicated_reference = reference.model_copy(
            deep=True,
            update={
                "duplicate_references": None,
            },
        )

        # Allows for reference chaining if settings.max_reference_duplicate_length>2
        duplicate_references = [
            DeduplicatedReferenceProjection.get_from_reference(reference)
            for reference in reference.duplicate_references
        ]

        # If None, we assume it was not preloaded. An empty reference with preloads
        # would have an empty list here instead.
        if deduplicated_reference.enhancements is not None:
            deduplicated_reference.enhancements += [
                enhancement
                for reference in duplicate_references
                for enhancement in reference.enhancements or []
            ]
        if deduplicated_reference.identifiers is not None:
            deduplicated_reference.identifiers += [
                identifier
                for reference in duplicate_references
                for identifier in (reference.identifiers or [])
            ]

        return deduplicated_reference
