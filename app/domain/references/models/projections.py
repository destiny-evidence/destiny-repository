"""Projection functions for reference domain data."""

import uuid

import destiny_sdk

from app.core.exceptions import ProjectionError
from app.domain.base import GenericProjection
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    PendingEnhancementStatus,
    Reference,
    ReferenceSearchFields,
)


class ReferenceSearchFieldsProjection(GenericProjection[ReferenceSearchFields]):
    """Projection functions for candidate selection used in duplicate detection."""

    @classmethod
    def get_from_reference(
        cls,
        reference: Reference,
    ) -> ReferenceSearchFields:
        """
        Get the candidate canonical search fields from a reference.

        :param reference: The reference to project from.
        :type reference: app.domain.references.models.models.Reference
        :raises ProjectionError: If the projection fails.
        :return: The projected candidate canonical search fields.
        :rtype: ReferenceSearchFields
        """
        try:
            title, publication_year = None, None
            abstract = None
            authorship: list[destiny_sdk.enhancements.Authorship] = []

            for enhancement in cls._priority_sorted_enhancements(
                canonical_id=reference.id, enhancements=reference.enhancements
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

                elif enhancement.content.enhancement_type == EnhancementType.ABSTRACT:
                    abstract = enhancement.content.abstract

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

            if abstract:
                abstract = abstract.strip()

        except Exception as exc:
            msg = "Failed to project ReferenceSearchFields from Reference"
            raise ProjectionError(msg) from exc

        return ReferenceSearchFields(
            abstract=abstract,
            authors=[author.display_name.strip() for author in authorship],
            publication_year=publication_year,
            title=title,
        )

    @classmethod
    def _priority_sorted_enhancements(
        cls, canonical_id: uuid.UUID, enhancements: list[Enhancement] | None
    ) -> list[Enhancement]:
        """
        Order a references enhancements by prioirty for projecting.

        Currently sorts in reverse order prioritising the canonical reference id.
        """
        return sorted(
            enhancements or [],
            # This preferences the canonical reference's enhancements
            # over those of its duplicates.
            key=lambda e: e.reference_id == canonical_id,
            reverse=True,
        )


class DeduplicatedReferenceProjection(GenericProjection[Reference]):
    """
    Projection functions for deduplicating canonical references.

    A deduplicated reference contains all the enhancements and identifiers of its
    duplicates, and is flattened to remove its duplicates. This makes it compatible
    with a SDK reference.

    TODO: Handle reference-level visibility.

    :param reference: The reference to project from.
    :type reference: app.domain.references.models.models.Reference
    :raises ProjectionError: If the projection fails.
    :return: The projected deduplicated reference.
    :rtype: Reference
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


class EnhancementRequestStatusProjection(GenericProjection[EnhancementRequest]):
    """Projection functions to hydrate enhancement request status."""

    @classmethod
    def get_from_status_set(
        cls,
        enhancement_request: EnhancementRequest,
        pending_enhancement_status_set: set[PendingEnhancementStatus],
    ) -> EnhancementRequest:
        """Project the enhancement request status from a set of pending statuses."""
        # No pending enhancements -> keep original status for backwards compatibility
        if not pending_enhancement_status_set:
            return enhancement_request

        # Define non-terminal statuses
        non_terminal_statuses = {
            PendingEnhancementStatus.PENDING,
            PendingEnhancementStatus.ACCEPTED,
            PendingEnhancementStatus.IMPORTING,
            PendingEnhancementStatus.INDEXING,
        }

        # All pending -> received
        if pending_enhancement_status_set == {PendingEnhancementStatus.PENDING}:
            enhancement_request.request_status = EnhancementRequestStatus.RECEIVED

        # If there are any non-terminal statuses, result should be PROCESSING
        elif non_terminal_statuses & pending_enhancement_status_set:
            enhancement_request.request_status = EnhancementRequestStatus.PROCESSING

        # Only terminal statuses remain - check their combination
        elif pending_enhancement_status_set == {PendingEnhancementStatus.COMPLETED}:
            enhancement_request.request_status = EnhancementRequestStatus.COMPLETED

        elif pending_enhancement_status_set == {PendingEnhancementStatus.FAILED}:
            enhancement_request.request_status = EnhancementRequestStatus.FAILED

        # Any other combination of terminal statuses -> partial failed
        else:
            enhancement_request.request_status = EnhancementRequestStatus.PARTIAL_FAILED

        return enhancement_request
