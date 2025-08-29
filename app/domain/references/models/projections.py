"""Projection functions for reference domain data."""

import destiny_sdk

from app.domain.base import GenericProjection
from app.domain.references.models.models import (
    CandidacyFingerprint,
    EnhancementType,
    ExternalIdentifierType,
    Fingerprint,
    Reference,
)


class CandidacyFingerprintProjection(GenericProjection[CandidacyFingerprint]):
    """Projection functions for candidate fingerprints used in duplicate detection."""

    @classmethod
    def get_from_reference(
        cls,
        reference: Reference,
    ) -> CandidacyFingerprint:
        """Get the candidate fingerprint from a reference."""
        title, authorship, publication_year = None, None, None
        for enhancement in reference.enhancements or []:
            # NB at present we have no way of discriminating between multiple
            # bibliographic enhancements, nor are they ordered. This takes a
            # random one (but hydrates in the case of one bibliographic enhancement
            # missing a field while the other has it present).
            if enhancement.content.enhancement_type == EnhancementType.BIBLIOGRAPHIC:
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
        # Then strip whitespace and title case
        if authorship:
            authorship = sorted(
                authorship,
                key=lambda author: (
                    {
                        destiny_sdk.enhancements.AuthorPosition.FIRST: -1,
                        destiny_sdk.enhancements.AuthorPosition.LAST: 1,
                    }.get(author.position, 0),
                    author.display_name,
                ),
            )

        return CandidacyFingerprint(
            title=title,
            authors=[author.display_name for author in authorship]
            if authorship
            else None,
            publication_year=publication_year,
        )

    @classmethod
    def get_from_fingerprint(cls, fingerprint: Fingerprint) -> CandidacyFingerprint:
        """Get the subset candidate fingerprint from a fingerprint."""
        return CandidacyFingerprint.model_validate(fingerprint, from_attributes=True)


class FingerprintProjection(GenericProjection[Fingerprint]):
    """Projection functions for de-duplication reference fingerprints."""

    @classmethod
    def get_from_reference(cls, reference: Reference) -> Fingerprint:
        """Get the fingerprint from a reference."""
        fingerprint = Fingerprint.model_validate(
            CandidacyFingerprintProjection.get_from_reference(reference),
            from_attributes=True,
        )

        for identifier in reference.identifiers or []:
            if identifier.identifier.identifier_type == ExternalIdentifierType.DOI:
                fingerprint.doi_identifier = identifier.identifier.identifier
            elif identifier.identifier.identifier_type == ExternalIdentifierType.PM_ID:
                fingerprint.pubmed_identifier = identifier.identifier.identifier
            elif (
                identifier.identifier.identifier_type
                == ExternalIdentifierType.OPEN_ALEX
            ):
                fingerprint.openalex_identifier = identifier.identifier.identifier
            elif identifier.identifier.identifier_type == ExternalIdentifierType.OTHER:
                fingerprint.other_identifiers[
                    identifier.identifier.other_identifier_name
                ] = identifier.identifier.identifier

        for enhancement in reference.enhancements or []:
            # Hydrate if exists on enhancement, otherwise use prior value
            if enhancement.content.enhancement_type == EnhancementType.BIBLIOGRAPHIC:
                fingerprint.publisher = (
                    enhancement.content.publisher or fingerprint.publisher
                )
            if enhancement.content.enhancement_type == EnhancementType.ABSTRACT:
                fingerprint.abstract = (
                    enhancement.content.abstract or fingerprint.abstract
                )

        return fingerprint
