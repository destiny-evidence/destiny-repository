"""Projection functions for reference domain data."""

import uuid
from collections import defaultdict

import destiny_sdk

from app.core.exceptions import ProjectionError
from app.domain.base import GenericProjection
from app.domain.references.models.models import (
    CandidateCanonicalSearchFields,
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

    # Registry of hardcoded annotations that are projected singly to the root
    # of the model. These are represented as (scheme, ?label).
    _singly_projected_annotations: tuple[tuple[str, str | None]] = (
        ("inclusion:destiny", None),
    )

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
            annotations_by_scheme: dict[
                str, list[destiny_sdk.enhancements.Annotation]
            ] = {}
            singly_projected_annotations: dict[
                tuple[str, str | None], destiny_sdk.enhancements.Annotation
            ] = {}

            for enhancement in cls.__priority_sorted_enhancements(
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

                elif enhancement.content.enhancement_type == EnhancementType.ANNOTATION:
                    # Pre-work: collect annotations by scheme, preserving the
                    # highest priority. Thus, if a scheme is processed twice,
                    # we only use the highest priority one. Coalescing is not
                    # performed, as an annotation that was once present that is missing
                    # in a later enhancement should be treated as removed.
                    #
                    # NB this makes the assumption that annotation schemes will always
                    # be wholly represented in a single enhancement.
                    _annotations_by_scheme: dict[
                        str, list[destiny_sdk.enhancements.Annotation]
                    ] = defaultdict(list)
                    for annotation in enhancement.content.annotations or []:
                        for key in [
                            (annotation.scheme, None),
                            (annotation.scheme, annotation.label),
                        ]:
                            if key in cls._singly_projected_annotations:
                                singly_projected_annotations[key] = annotation

                        _annotations_by_scheme[annotation.scheme].append(annotation)

                    annotations_by_scheme |= _annotations_by_scheme

            annotations = cls.__positive_boolean_annotations(annotations_by_scheme)

            destiny_inclusion_annotation = singly_projected_annotations.get(
                ("inclusion:destiny", None)
            )

            return ReferenceSearchFields(
                abstract=abstract,
                authors=cls.__order_authorship_by_position(authorship),
                publication_year=publication_year,
                title=title,
                annotations=annotations,
                evaluated_schemes=annotations_by_scheme.keys(),
                destiny_inclusion_score=cls.__positive_annotation_score(
                    destiny_inclusion_annotation
                ),
            )

        except Exception as exc:
            msg = "Failed to project ReferenceSearchFields from Reference"
            raise ProjectionError(msg) from exc

    @classmethod
    def __order_authorship_by_position(
        cls, authorship: list[destiny_sdk.enhancements.Authorship]
    ) -> list[str]:
        """Order authorship by position: first, middle (alphabetical), last."""
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

    @classmethod
    def __priority_sorted_enhancements(
        cls, canonical_id: uuid.UUID, enhancements: list[Enhancement] | None
    ) -> list[Enhancement]:
        """
        Order a references enhancements by priority for projecting in increasing order.

        Prioritiy is defined as
        * Firstly, we prioritize enhancements on the canonical reference
        * Secondly, we prioritize most recent enhancements

        Concretely
        * If there's an abstract on the canonical, use that
        * If there's two abstracts on the canonical, use the most recent
        * If there's no abstracts on the canonical, use the most recent
        abstract from all duplicates.

        So this function places the highest priority enhancement at the end of the list.
        """
        if not enhancements:
            return []

        def __priority_sort_key(
            canonical_id: uuid.UUID, enhancement: Enhancement
        ) -> tuple[bool, float]:
            """Key for sorting enhancements."""
            if not enhancement.created_at:
                msg = "We should never try to project an enhancement without created_at"
                raise RuntimeError(msg)

            return (
                enhancement.reference_id == canonical_id,
                enhancement.created_at.timestamp(),
            )

        return sorted(enhancements, key=lambda e: __priority_sort_key(canonical_id, e))

    @classmethod
    def __positive_boolean_annotations(
        cls,
        annotations_by_scheme: dict[str, list[destiny_sdk.enhancements.Annotation]],
    ) -> set[str]:
        """Process annotations into a set of positive annotation labels."""
        return {
            annotation.qualified_label
            for annotations in annotations_by_scheme.values()
            for annotation in annotations
            if (
                annotation.annotation_type
                == destiny_sdk.enhancements.AnnotationType.BOOLEAN
                and annotation.value
            )
        }

    @classmethod
    def __positive_annotation_score(
        cls,
        annotation: destiny_sdk.enhancements.Annotation | None,
    ) -> float | None:
        """
        Get the score of an annotation.

        If the annotation is boolean, return the truth score (i.e. inverted if false).
        """
        if not annotation:
            return None
        if (inclusion_score := annotation.data.get("inclusion_score")) is not None:
            return inclusion_score
        if (
            annotation.annotation_type
            == destiny_sdk.enhancements.AnnotationType.BOOLEAN
            and annotation.score is not None
        ):
            return annotation.score if annotation.value else 1 - annotation.score
        if annotation.annotation_type == (
            destiny_sdk.enhancements.AnnotationType.SCORE
        ):
            return annotation.score
        return None

    @classmethod
    def get_canonical_candidate_search_fields(
        cls, reference: Reference
    ) -> CandidateCanonicalSearchFields:
        """Return fields needed for candidate canonical selection."""
        return cls.get_from_reference(reference).to_canonical_candidate_search_fields()


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
        # Ignore expired pending enhancements, they have no weight
        pending_enhancement_status_set.discard(PendingEnhancementStatus.EXPIRED)

        # No pending enhancements -> keep original status for backwards compatibility
        if not pending_enhancement_status_set:
            return enhancement_request

        # Define non-terminal statuses
        non_terminal_statuses = {
            PendingEnhancementStatus.PENDING,
            PendingEnhancementStatus.PROCESSING,
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
