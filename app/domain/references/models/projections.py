"""Projection functions for reference domain data."""

from collections import defaultdict
from typing import ClassVar
from uuid import UUID

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
from app.domain.references.models.ris import RisRecord, RisType


def _priority_sorted_enhancements(
    canonical_id: UUID, enhancements: list[Enhancement] | None
) -> list[Enhancement]:
    """
    Order a references enhancements by priority for projecting in increasing order.

    Priority is defined as
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

    def _sort_key(enhancement: Enhancement) -> tuple[bool, float]:
        if not enhancement.created_at:
            msg = "We should never try to project an enhancement without created_at"
            raise RuntimeError(msg)
        return (
            enhancement.reference_id == canonical_id,
            enhancement.created_at.timestamp(),
        )

    return sorted(enhancements, key=_sort_key)


def _order_authorship_by_position(
    authorship: list[destiny_sdk.enhancements.Authorship],
    *,
    alphabetize_within_position: bool = True,
) -> list[str]:
    """
    Order authorship FIRST, then MIDDLE, then LAST.

    ``position`` has no ordinal, so middle authors tie. The default breaks ties by
    name (deterministic, for search); ``alphabetize_within_position=False`` keeps
    their stored order, which is generally the true citation sequence.
    """

    def _sort_key(
        author: destiny_sdk.enhancements.Authorship,
    ) -> tuple[int, str]:
        position_rank = {
            destiny_sdk.enhancements.AuthorPosition.FIRST: -1,
            destiny_sdk.enhancements.AuthorPosition.LAST: 1,
        }.get(author.position, 0)
        tiebreak = author.display_name if alphabetize_within_position else ""
        return (position_rank, tiebreak)

    return [author.display_name for author in sorted(authorship, key=_sort_key)]


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
            title, publication_year, publication_date = None, None, None
            abstract = None
            authorship: list[destiny_sdk.enhancements.Authorship] = []
            annotations_by_scheme: dict[
                str, list[destiny_sdk.enhancements.Annotation]
            ] = {}
            singly_projected_annotations: dict[
                tuple[str, str | None], destiny_sdk.enhancements.Annotation
            ] = {}
            linked_data_content = None

            for enhancement in _priority_sorted_enhancements(
                reference.id, reference.enhancements
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

                    publication_date = (
                        enhancement.content.publication_date or publication_date
                    )

                elif enhancement.content.enhancement_type == EnhancementType.ABSTRACT:
                    abstract = enhancement.content.abstract

                elif (
                    enhancement.content.enhancement_type == EnhancementType.LINKED_DATA
                ):
                    linked_data_content = enhancement.content

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
                authors=_order_authorship_by_position(authorship),
                publication_date=publication_date,
                publication_year=publication_year,
                title=title,
                annotations=annotations,
                evaluated_schemes=annotations_by_scheme.keys(),
                destiny_inclusion_score=cls.__positive_annotation_score(
                    destiny_inclusion_annotation
                ),
                linked_data_content=linked_data_content,
            )

        except Exception as exc:
            msg = "Failed to project ReferenceSearchFields from Reference"
            raise ProjectionError(msg) from exc

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


class ReferenceRisProjection(GenericProjection[RisRecord]):
    """Projection from a reference to an ``RisRecord`` for RIS export."""

    DATABASE_NAME: ClassVar[str] = "Evidence Repository"

    IDENTIFIER_URL_TEMPLATES: ClassVar[
        dict[destiny_sdk.identifiers.ExternalIdentifierType, str]
    ] = {
        destiny_sdk.identifiers.ExternalIdentifierType.DOI: "https://doi.org/{}",
        destiny_sdk.identifiers.ExternalIdentifierType.PM_ID: (
            "https://pubmed.ncbi.nlm.nih.gov/{}/"
        ),
        destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX: (
            "https://openalex.org/{}"
        ),
        destiny_sdk.identifiers.ExternalIdentifierType.ERIC: "https://eric.ed.gov/?id={}",
        destiny_sdk.identifiers.ExternalIdentifierType.PRO_QUEST: (
            "https://www.proquest.com/docview/{}"
        ),
    }

    VENUE_TYPE_TO_RIS_TYPE: ClassVar[
        dict[destiny_sdk.enhancements.PublicationVenueType, RisType]
    ] = {
        destiny_sdk.enhancements.PublicationVenueType.JOURNAL: RisType.JOURNAL,
        destiny_sdk.enhancements.PublicationVenueType.CONFERENCE: RisType.CONFERENCE,
        destiny_sdk.enhancements.PublicationVenueType.REPOSITORY: RisType.GENERIC,
        destiny_sdk.enhancements.PublicationVenueType.BOOK_SERIES: RisType.SERIAL,
        destiny_sdk.enhancements.PublicationVenueType.EBOOK_PLATFORM: RisType.BOOK,
        destiny_sdk.enhancements.PublicationVenueType.OTHER: RisType.GENERIC,
    }

    @classmethod
    def get_from_reference(cls, reference: Reference) -> RisRecord:
        """Project an ``RisRecord``, coalescing enhancement fields by priority."""
        try:
            (
                title,
                publication_year,
                publication_date,
                publisher,
                abstract,
                pagination,
                venue,
                pdf_url,
            ) = None, None, None, None, None, None, None, None
            authorship: list[destiny_sdk.enhancements.Authorship] = []
            urls: list[str] = []

            for enhancement in _priority_sorted_enhancements(
                reference.id, reference.enhancements
            ):
                if (
                    enhancement.content.enhancement_type
                    == EnhancementType.BIBLIOGRAPHIC
                ):
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
                    publication_date = (
                        enhancement.content.publication_date or publication_date
                    )
                    publisher = enhancement.content.publisher or publisher
                    pagination = enhancement.content.pagination or pagination
                    venue = enhancement.content.publication_venue or venue
                elif enhancement.content.enhancement_type == EnhancementType.ABSTRACT:
                    abstract = enhancement.content.abstract
                elif enhancement.content.enhancement_type == EnhancementType.LOCATION:
                    locations = enhancement.content.locations
                    urls = [
                        str(location.landing_page_url)
                        for location in locations
                        if location.landing_page_url
                    ] or urls
                    pdf_url = next(
                        (
                            str(location.pdf_url)
                            for location in locations
                            if location.pdf_url
                        ),
                        pdf_url,
                    )

            return RisRecord(
                reference_type=cls._ris_type(venue),
                title=title,
                authors=_order_authorship_by_position(
                    authorship, alphabetize_within_position=False
                ),
                publication_year=publication_year,
                publication_date=publication_date,
                journal=venue.display_name if venue else None,
                volume=pagination.volume if pagination else None,
                issue=pagination.issue if pagination else None,
                start_page=pagination.first_page if pagination else None,
                end_page=pagination.last_page if pagination else None,
                publisher=publisher
                or (venue.host_organization_name if venue else None),
                issns=venue.issn if venue and venue.issn else [],
                abstract=abstract,
                doi=cls._identifier_value(
                    reference, destiny_sdk.identifiers.ExternalIdentifierType.DOI
                ),
                accession=str(reference.id),
                database=cls.DATABASE_NAME,
                pdf_url=pdf_url,
                urls=list(dict.fromkeys(urls + cls._identifier_urls(reference))),
            )
        except Exception as exc:
            msg = "Failed to project RisRecord from Reference"
            raise ProjectionError(msg) from exc

    @classmethod
    def _ris_type(
        cls, venue: destiny_sdk.enhancements.PublicationVenue | None
    ) -> RisType:
        """Map a publication venue to an RIS type, defaulting to generic."""
        if venue and venue.venue_type:
            return cls.VENUE_TYPE_TO_RIS_TYPE.get(venue.venue_type, RisType.GENERIC)
        return RisType.GENERIC

    @staticmethod
    def _identifier_value(
        reference: Reference,
        identifier_type: destiny_sdk.identifiers.ExternalIdentifierType,
    ) -> str | None:
        """Return the first matching external identifier value, if present."""
        for linked in reference.identifiers or []:
            if linked.identifier.identifier_type == identifier_type:
                return str(linked.identifier.identifier)
        return None

    @classmethod
    def _identifier_urls(cls, reference: Reference) -> list[str]:
        """Resolve external identifiers to public URLs for the `UR` tag."""
        urls = []
        for linked in reference.identifiers or []:
            template = cls.IDENTIFIER_URL_TEMPLATES.get(
                linked.identifier.identifier_type
            )
            if template:
                urls.append(template.format(linked.identifier.identifier))
        return urls


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

        if deduplicated_reference.enhancements is not None:
            deduplicated_reference.enhancements += [
                enhancement
                for ref in reference.duplicate_references
                for enhancement in ref.enhancements or []
            ]
        if deduplicated_reference.identifiers is not None:
            deduplicated_reference.identifiers += [
                identifier
                for ref in reference.duplicate_references
                for identifier in (ref.identifiers or [])
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
