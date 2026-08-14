from datetime import UTC, datetime

import pytest
from destiny_sdk.enhancements import AuthorPosition

from app.core.exceptions import ProjectionError
from app.domain.references.models.models import Reference
from app.domain.references.models.projections import DeduplicationPaperProjection
from tests.factories import (
    AbstractContentEnhancementFactory,
    AuthorshipFactory,
    BibliographicMetadataEnhancementFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    FullTextEnhancementFactory,
    LinkedExternalIdentifierFactory,
    LocationEnhancementFactory,
    LocationFactory,
    OpenAlexIdentifierFactory,
    PaginationFactory,
    PublicationVenueFactory,
    PubMedIdentifierFactory,
    ReferenceFactory,
)


def _reference(*, enhancement_contents=None, identifiers=None, **kwargs) -> Reference:
    """Build a reference whose children carry its id, as stored records do."""
    reference = ReferenceFactory.build(**kwargs)
    return reference.model_copy(
        update={
            "enhancements": [
                EnhancementFactory.build(reference_id=reference.id, content=content)
                for content in (enhancement_contents or [])
            ],
            "identifiers": [
                LinkedExternalIdentifierFactory.build(
                    reference_id=reference.id, identifier=identifier
                )
                for identifier in (identifiers or [])
            ],
        }
    )


def test_projects_scored_identifiers():
    doi = DOIIdentifierFactory.build()
    open_alex = OpenAlexIdentifierFactory.build()
    pubmed = PubMedIdentifierFactory.build()
    reference = _reference(
        enhancement_contents=[BibliographicMetadataEnhancementFactory.build()],
        identifiers=[doi, open_alex, pubmed],
    )

    paper = DeduplicationPaperProjection.get_from_reference(reference)

    assert paper.doi == doi
    assert paper.openalex_id == open_alex
    assert paper.pubmed_id == pubmed


def test_projects_bibliographic_fields():
    content = BibliographicMetadataEnhancementFactory.build(
        title="Trial of a thing",
        publication_year=2024,
        publication_venue=PublicationVenueFactory.build(display_name="The Lancet"),
        pagination=PaginationFactory.build(
            volume="12", issue="4", first_page="101", last_page="115"
        ),
    )
    reference = _reference(enhancement_contents=[content])

    paper = DeduplicationPaperProjection.get_from_reference(reference)

    assert paper.title == "Trial of a thing"
    assert paper.year == 2024
    assert paper.journal == "The Lancet"
    assert paper.volume == "12"
    assert paper.issue == "4"
    assert paper.pages == "101-115"


def test_pages_needs_both_endpoints():
    content = BibliographicMetadataEnhancementFactory.build(
        pagination=PaginationFactory.build(first_page="101", last_page=None)
    )
    reference = _reference(enhancement_contents=[content])

    assert DeduplicationPaperProjection.get_from_reference(reference).pages is None


def test_authors_keep_stored_order():
    # Stored order is the citation sequence. The shared authorship helper
    # alphabetises within position, which would scramble it.
    authorship = [
        AuthorshipFactory.build(
            display_name="Zoe Alvarez", position=AuthorPosition.FIRST
        ),
        AuthorshipFactory.build(
            display_name="Yusuf Bello", position=AuthorPosition.MIDDLE
        ),
        AuthorshipFactory.build(
            display_name="Alice Crane", position=AuthorPosition.MIDDLE
        ),
    ]
    reference = _reference(
        enhancement_contents=[
            BibliographicMetadataEnhancementFactory.build(authorship=authorship)
        ]
    )

    paper = DeduplicationPaperProjection.get_from_reference(reference)

    assert [author.display_name for author in paper.authors or []] == [
        "Zoe Alvarez",
        "Yusuf Bello",
        "Alice Crane",
    ]


def test_year_falls_back_to_publication_date():
    content = BibliographicMetadataEnhancementFactory.build(
        publication_year=None, publication_date=datetime(2019, 6, 1, tzinfo=UTC).date()
    )
    reference = _reference(enhancement_contents=[content])

    assert DeduplicationPaperProjection.get_from_reference(reference).year == 2019


def test_ignores_non_bibliographic_enhancements():
    reference = _reference(
        enhancement_contents=[
            BibliographicMetadataEnhancementFactory.build(title="Only this"),
            AbstractContentEnhancementFactory.build(),
            FullTextEnhancementFactory.build(),
        ]
    )

    paper = DeduplicationPaperProjection.get_from_reference(reference)

    assert paper.title == "Only this"
    assert "abstract" not in paper.model_dump()


def test_venue_never_comes_from_a_location_enhancement():
    # The toolkit's own converter reads journal, issn, volume and issue out of a
    # LOCATION extra dict. Sourcing those here instead is the point of this
    # projection, so a LOCATION carrying venue data must not reach the paper.
    reference = _reference(
        enhancement_contents=[
            BibliographicMetadataEnhancementFactory.build(
                publication_venue=PublicationVenueFactory.build(
                    display_name="The Lancet"
                ),
                pagination=PaginationFactory.build(volume="12", issue="4"),
            ),
            LocationEnhancementFactory.build(
                locations=[
                    LocationFactory.build(
                        extra={
                            "display_name": "PubMed",
                            "volume": "999",
                            "issue": "999",
                        }
                    )
                ]
            ),
        ]
    )

    paper = DeduplicationPaperProjection.get_from_reference(reference)

    assert paper.journal == "The Lancet"
    assert paper.volume == "12"
    assert paper.issue == "4"


def test_highest_priority_bibliographic_enhancement_wins():
    reference = ReferenceFactory.build()
    older = EnhancementFactory.build(
        reference_id=reference.id,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        content=BibliographicMetadataEnhancementFactory.build(title="Older title"),
    )
    newer = EnhancementFactory.build(
        reference_id=reference.id,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        content=BibliographicMetadataEnhancementFactory.build(title="Newer title"),
    )
    reference = reference.model_copy(update={"enhancements": [newer, older]})

    paper = DeduplicationPaperProjection.get_from_reference(reference)

    assert paper.title == "Newer title"


def test_missing_fields_fall_back_to_a_lower_priority_enhancement():
    reference = ReferenceFactory.build()
    older = EnhancementFactory.build(
        reference_id=reference.id,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        content=BibliographicMetadataEnhancementFactory.build(
            title="Older title",
            publication_venue=PublicationVenueFactory.build(display_name="The Lancet"),
        ),
    )
    newer = EnhancementFactory.build(
        reference_id=reference.id,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        content=BibliographicMetadataEnhancementFactory.build(
            title="Newer title", publication_venue=None
        ),
    )
    reference = reference.model_copy(update={"enhancements": [older, newer]})

    paper = DeduplicationPaperProjection.get_from_reference(reference)

    assert paper.title == "Newer title"
    assert paper.journal == "The Lancet"


def test_projects_supplied_reference_without_created_at():
    # A supplied record is built in memory, so its enhancements carry no created_at.
    # The shared priority sort raises RuntimeError on those.
    reference = ReferenceFactory.build()
    reference = reference.model_copy(
        update={
            "enhancements": [
                EnhancementFactory.build(
                    reference_id=reference.id,
                    created_at=None,
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="A supplied reference"
                    ),
                )
            ]
        }
    )

    paper = DeduplicationPaperProjection.get_from_reference(reference)

    assert paper.title == "A supplied reference"


def test_untimed_enhancements_keep_input_order():
    reference = ReferenceFactory.build()
    reference = reference.model_copy(
        update={
            "enhancements": [
                EnhancementFactory.build(
                    reference_id=reference.id,
                    created_at=None,
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="First"
                    ),
                ),
                EnhancementFactory.build(
                    reference_id=reference.id,
                    created_at=None,
                    content=BibliographicMetadataEnhancementFactory.build(title="Last"),
                ),
            ]
        }
    )

    assert DeduplicationPaperProjection.get_from_reference(reference).title == "Last"


def test_raises_when_nothing_projects():
    reference = _reference(enhancement_contents=[], identifiers=[])

    with pytest.raises(ProjectionError):
        DeduplicationPaperProjection.get_from_reference(reference)
