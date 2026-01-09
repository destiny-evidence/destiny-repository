"""Unit tests for the projection functions in the references module."""

import uuid
from datetime import UTC, date, datetime, timedelta
from math import isclose
from random import shuffle

import destiny_sdk
import pytest

from app.core.exceptions import ProjectionError
from app.domain.references.models.models import (
    Enhancement,
    EnhancementType,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
    Visibility,
)
from app.domain.references.models.projections import (
    DeduplicatedReferenceProjection,
    ReferenceSearchFieldsProjection,
)
from tests.factories import (
    AbstractContentEnhancementFactory,
    AnnotationEnhancementFactory,
    AuthorshipFactory,
    BibliographicMetadataEnhancementFactory,
    BooleanAnnotationFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    ERICIdentifierFactory,
    LinkedExternalIdentifierFactory,
    OpenAlexIdentifierFactory,
    OtherIdentifierFactory,
    PubMedIdentifierFactory,
    RawEnhancementFactory,
    ReferenceFactory,
    ScoreAnnotationFactory,
)


@pytest.fixture
def sample_authorship():
    """Create sample authorship data."""
    return [
        AuthorshipFactory.build(
            display_name="John Smith",
            orcid="0000-0000-0000-0001",
            position=destiny_sdk.enhancements.AuthorPosition.FIRST,
        ),
        AuthorshipFactory.build(
            display_name="Alice Johnson",
            orcid="0000-0000-0000-0002",
            position=destiny_sdk.enhancements.AuthorPosition.MIDDLE,
        ),
        AuthorshipFactory.build(
            display_name="Bob Williams",
            orcid=None,
            position=destiny_sdk.enhancements.AuthorPosition.LAST,
        ),
    ]


@pytest.fixture
def bibliographic_enhancement(sample_authorship):
    """Create a bibliographic enhancement."""
    bibliographic_content = BibliographicMetadataEnhancementFactory.build(
        title="Sample Research Paper",
        authorship=sample_authorship,
        publication_date=datetime(year=2023, month=4, day=2, tzinfo=UTC),
    )

    return EnhancementFactory.build(
        content=bibliographic_content, created_at=datetime.now(tz=UTC)
    )


@pytest.fixture
def abstract_enhancement():
    """Create an abstract enhancement."""
    abstract_content = AbstractContentEnhancementFactory.build(
        abstract="This is a sample abstract for testing purposes.",
    )

    return EnhancementFactory.build(
        content=abstract_content, source="test_source", created_at=datetime.now(tz=UTC)
    )


@pytest.fixture
def destiny_inclusion_annotation_enhancement():
    """Create an enhancement with a destiny inclusion annotation."""
    annotation = BooleanAnnotationFactory.build(
        scheme="inclusion:destiny", value=True, score=0.8
    )
    return EnhancementFactory.build(
        content=AnnotationEnhancementFactory.build(annotations=[annotation]),
        created_at=datetime.now(tz=UTC),
    )


@pytest.fixture
def taxonomy_annotation_enhancement():
    """Create an enhancement with a taxonomy annotation."""
    annotations = BooleanAnnotationFactory.build_batch(
        size=10, scheme="taxonomy:science"
    )
    return EnhancementFactory.build(
        content=AnnotationEnhancementFactory.build(annotations=annotations),
        created_at=datetime.now(tz=UTC),
    )


@pytest.fixture
def doi_identifier():
    """Create a DOI identifier."""
    return LinkedExternalIdentifierFactory.build(
        identifier=DOIIdentifierFactory.build(identifier="10.1000/abc123")
    )


@pytest.fixture
def eric_identifier():
    """Create an ERIC identifier"""
    return LinkedExternalIdentifierFactory.build(
        identifier=ERICIdentifierFactory.build(identifier="ED325323")
    )


@pytest.fixture
def pubmed_identifier():
    """Create a PubMed identifier."""
    return LinkedExternalIdentifierFactory.build(
        identifier=PubMedIdentifierFactory.build(identifier=12345678)
    )


@pytest.fixture
def openalex_identifier():
    """Create an OpenAlex identifier."""
    return LinkedExternalIdentifierFactory.build(
        identifier=OpenAlexIdentifierFactory.build(identifier="W1234567890")
    )


@pytest.fixture
def other_identifier():
    """Create an other identifier."""
    return LinkedExternalIdentifierFactory.build(
        identifier=OtherIdentifierFactory.build(
            identifier="978-0123456789",
            other_identifier_name="ISBN",
        )
    )


@pytest.fixture
def reference_with_enhancements(bibliographic_enhancement, abstract_enhancement):
    """Create a reference with enhancements."""
    ref_id = uuid.uuid7()

    bibliographic_enhancement.reference_id = ref_id
    abstract_enhancement.reference_id = ref_id

    return ReferenceFactory.build(
        id=ref_id,
        enhancements=[bibliographic_enhancement, abstract_enhancement],
        identifiers=[],
    )


@pytest.fixture
def reference_with_annotations(
    destiny_inclusion_annotation_enhancement,
    taxonomy_annotation_enhancement,
):
    """Create a reference with annotation enhancements."""
    ref_id = uuid.uuid7()

    destiny_inclusion_annotation_enhancement.reference_id = ref_id
    taxonomy_annotation_enhancement.reference_id = ref_id

    return ReferenceFactory.build(
        id=ref_id,
        enhancements=[
            destiny_inclusion_annotation_enhancement,
            taxonomy_annotation_enhancement,
        ],
        identifiers=[],
    )


@pytest.fixture
def complete_reference(
    doi_identifier,
    eric_identifier,
    pubmed_identifier,
    openalex_identifier,
    other_identifier,
    bibliographic_enhancement,
    abstract_enhancement,
    destiny_inclusion_annotation_enhancement,
    taxonomy_annotation_enhancement,
):
    """Create a reference with both enhancements and identifiers."""
    ref_id = uuid.uuid7()

    # Update the identifier IDs to match
    doi_identifier.reference_id = ref_id
    eric_identifier.reference_id = ref_id
    pubmed_identifier.reference_id = ref_id
    openalex_identifier.reference_id = ref_id
    other_identifier.reference_id = ref_id

    # Update enhancement reference IDs to match
    bibliographic_enhancement.reference_id = ref_id
    abstract_enhancement.reference_id = ref_id
    destiny_inclusion_annotation_enhancement.reference_id = ref_id
    taxonomy_annotation_enhancement.reference_id = ref_id
    doi_identifier.reference_id = ref_id
    pubmed_identifier.reference_id = ref_id

    # Add a raw enhancement
    raw_enhancement = EnhancementFactory.build(
        reference_id=ref_id, content=RawEnhancementFactory.build()
    )

    return ReferenceFactory.build(
        id=ref_id,
        enhancements=[
            bibliographic_enhancement,
            abstract_enhancement,
            destiny_inclusion_annotation_enhancement,
            taxonomy_annotation_enhancement,
            raw_enhancement,
        ],
        identifiers=[
            doi_identifier,
            eric_identifier,
            pubmed_identifier,
            openalex_identifier,
            other_identifier,
        ],
    )


class TestReferenceSearchFieldsProjection:
    """Test the ReferenceSearchFieldsProjection class."""

    def test_reference_sorting_prioritises_canonical(
        self, bibliographic_enhancement, sample_authorship
    ):
        """Test that we prioritise canonical enhancements"""
        reference_id = uuid.uuid7()

        canonical_biblography = EnhancementFactory.build(
            reference_id=reference_id,
            content=BibliographicMetadataEnhancementFactory.build(
                title="We get this title, this enhancement is on canonical reference",
                authorship=sample_authorship,
                publication_date=datetime(year=2021, month=2, day=17, tzinfo=UTC),
            ),
        )

        reference = ReferenceFactory.build(
            id=reference_id,
            enhancements=[bibliographic_enhancement, canonical_biblography],
        )

        reference_proj = ReferenceSearchFieldsProjection.get_from_reference(reference)
        assert reference_proj.title == canonical_biblography.content.title

    def test_reference_sorting_prioritises_created_date(
        self, bibliographic_enhancement, sample_authorship
    ):
        """Test that we prioritise the created date of the enhancements"""
        reference_id = uuid.uuid7()

        most_recent_bibliography = EnhancementFactory.build(
            # Created the day after the the other bibliographic enhancement
            created_at=bibliographic_enhancement.created_at + timedelta(days=1),
            content=BibliographicMetadataEnhancementFactory.build(
                title="We get this title, it's the most recent enhancement",
                authorship=sample_authorship,
                publication_date=datetime(year=2021, month=2, day=17, tzinfo=UTC),
            ),
        )

        reference = ReferenceFactory.build(
            id=reference_id,
            enhancements=[most_recent_bibliography, bibliographic_enhancement],
        )

        reference_proj = ReferenceSearchFieldsProjection.get_from_reference(reference)
        assert reference_proj.title == most_recent_bibliography.content.title

    def test_reference_sorting_priorises_canonical_over_most_recent(
        self, bibliographic_enhancement, sample_authorship
    ):
        """
        Test prioritisation rule order.

        When an enhancement on a duplicate reference is more recent than an
        enhancement on the canonical reference, we still use the enhancement
        on the canonical reference.
        """
        reference_id = uuid.uuid7()
        bibliographic_enhancement.reference_id = reference_id

        most_recent_bibliography = EnhancementFactory.build(
            content=BibliographicMetadataEnhancementFactory.build(
                title="We don't get this title, there's a canonical bibliography.",
                authorship=sample_authorship,
                publication_date=datetime(year=2021, month=2, day=17, tzinfo=UTC),
            ),
            # Created more recently than the other bibliographic enhancement
            created_at=bibliographic_enhancement.created_at + timedelta(days=1),
        )

        reference = ReferenceFactory.build(
            id=reference_id,
            enhancements=[bibliographic_enhancement, most_recent_bibliography],
        )

        reference_proj = ReferenceSearchFieldsProjection.get_from_reference(reference)
        assert reference_proj.title == bibliographic_enhancement.content.title

    def test_reference_sorting_the_uber_refrence(
        self,
        bibliographic_enhancement: Enhancement,
        abstract_enhancement: Enhancement,
        taxonomy_annotation_enhancement: Enhancement,
        destiny_inclusion_annotation_enhancement: Enhancement,
        sample_authorship,
    ):
        """
        Big sort test on projecting a reference with the following enhancements

        * A canonical bibliography
        * A more recent canonical bibliography
        * A canonical abstract
        * A more recent canonical abstract
        * A taxonomy annotation
        * A more recent taxonomy annotation
        * A destiny inclusion annotation
        * A more recent destiny inclusion annotation
        * A duplicate bibliography that is the most recent
        * A duplicate reference abstract that is the most recent

        This test also shuffles the enhancements before adding them to the reference.
        """
        canonical_reference_id = uuid.uuid7()

        # Make our two pre-generated enhancements canonical
        bibliographic_enhancement.reference_id = canonical_reference_id
        abstract_enhancement.reference_id = canonical_reference_id

        assert bibliographic_enhancement.created_at
        assert abstract_enhancement.created_at
        assert taxonomy_annotation_enhancement.created_at
        assert destiny_inclusion_annotation_enhancement.created_at

        most_recent_canonical_bibliography = EnhancementFactory.build(
            reference_id=canonical_reference_id,
            content=BibliographicMetadataEnhancementFactory.build(
                title="We should get this title, most recent canonical bibliography",
                authorship=sample_authorship,
            ),
            # Created more recently than the other canonical bibliographic enhancement
            created_at=bibliographic_enhancement.created_at + timedelta(days=1),
        )

        most_recent_bibliography_duplicate_reference = EnhancementFactory.build(
            content=BibliographicMetadataEnhancementFactory.build(
                title="We should not get this title, it's a duplicate",
            ),
            # Created more recently than all other bibliographies
            created_at=(
                most_recent_canonical_bibliography.created_at + timedelta(days=1)
            ),
        )

        most_recent_taxonomy_annotation = EnhancementFactory.build(
            content=AnnotationEnhancementFactory.build(
                annotations=[
                    BooleanAnnotationFactory.build(
                        scheme="taxonomy:science", label="label!", value=True
                    ),
                    BooleanAnnotationFactory.build(
                        scheme="taxonomy:science", label="foobar", value=False
                    ),
                ]
            ),
            created_at=taxonomy_annotation_enhancement.created_at + timedelta(days=1),
        )

        most_recent_destiny_inclusion_annotation = EnhancementFactory.build(
            content=AnnotationEnhancementFactory.build(
                annotations=[
                    BooleanAnnotationFactory.build(
                        scheme="inclusion:destiny", value=False, score=0.8
                    )
                ]
            ),
            created_at=destiny_inclusion_annotation_enhancement.created_at
            + timedelta(days=1),
        )

        most_recent_canonical_abstract = EnhancementFactory.build(
            reference_id=canonical_reference_id,
            content=AbstractContentEnhancementFactory.build(
                abstract="We should get this abstract, most recent canonical abstract."
            ),
            # Created more recently than the other canonical abstract enhancement
            created_at=abstract_enhancement.created_at + timedelta(days=1),
        )

        most_recent_abstract_duplicate_reference = EnhancementFactory.build(
            content=AbstractContentEnhancementFactory.build(
                abstract="We should not get this abstract, it's from a duplicate"
            ),
            # Created more recently than all other abstracts
            created_at=most_recent_canonical_abstract.created_at + timedelta(days=1),
        )

        enhancements = [
            bibliographic_enhancement,
            most_recent_canonical_bibliography,
            most_recent_bibliography_duplicate_reference,
            abstract_enhancement,
            most_recent_canonical_abstract,
            most_recent_abstract_duplicate_reference,
            taxonomy_annotation_enhancement,
            most_recent_taxonomy_annotation,
            destiny_inclusion_annotation_enhancement,
            most_recent_destiny_inclusion_annotation,
        ]

        shuffle(enhancements)

        uber_reference = ReferenceFactory.build(
            id=canonical_reference_id, enhancements=enhancements
        )

        result = ReferenceSearchFieldsProjection.get_from_reference(uber_reference)

        assert result.abstract == most_recent_canonical_abstract.content.abstract
        # Assert on expected authors from sample_authors
        assert result.authors[0] == "John Smith"  # Whitespace stripped
        assert result.authors[1] == "Alice Johnson"  # Middle author
        assert result.authors[2] == "Bob Williams"  # Last author

        assert result.publication_year == (
            most_recent_canonical_bibliography.content.publication_year
        )

        assert result.title == most_recent_canonical_bibliography.content.title

        assert result.annotations == ["taxonomy:science/label!"]
        assert set(result.evaluated_schemes) == {
            "taxonomy:science",
            "inclusion:destiny",
        }
        assert result.destiny_inclusion_score
        assert isclose(result.destiny_inclusion_score, 0.2)

    def test_get_from_reference_hydrate_missing_bibliography_information(
        self, sample_authorship
    ):
        """Test that we hydrate missing data from lower prioritiy references."""
        enhancement_with_title = EnhancementFactory.build(
            source="hydration_source1",
            content=BibliographicMetadataEnhancementFactory.build(
                title="Hydration Title",  # This should be used
                authorship=[],
                publication_date=None,
            ),
            created_at=datetime(year=2021, month=2, day=17, tzinfo=UTC),
        )

        enhancement_with_authors = EnhancementFactory.build(
            source="hydration_source2",
            content=BibliographicMetadataEnhancementFactory.build(
                title=None,
                authorship=sample_authorship,
                publication_date=None,
            ),
            # Enhancement is created 1 year after the enhancement with title
            created_at=enhancement_with_title.created_at + timedelta(days=365),
        )

        enhancement_with_publication_date = EnhancementFactory.build(
            source="hydration_source3",
            content=BibliographicMetadataEnhancementFactory.build(
                title=None,
                authorship=[],
                publication_date=datetime(year=1985, month=3, day=11, tzinfo=UTC),
            ),
            # Enhancement is created 1 year before the enhancement with title
            created_at=enhancement_with_title.created_at - timedelta(days=365),
        )

        reference = Reference(
            id=uuid.uuid7(),
            visibility=Visibility.PUBLIC,
            enhancements=[
                enhancement_with_title,
                enhancement_with_authors,
                enhancement_with_publication_date,
            ],
            identifiers=[],
        )

        result = ReferenceSearchFieldsProjection.get_from_reference(reference)
        assert result.title == enhancement_with_title.content.title
        assert result.publication_year == (
            enhancement_with_publication_date.content.publication_year
        )
        assert len(result.authors) == len(enhancement_with_authors.content.authorship)

    def test_get_from_reference_handles_whitespace_and_author_ordering(self):
        """
        Test that we strip whitespace from authors, titles, and abstracts.

        Also test that authors are returned with correct positions
        """
        canonical_reference_id = uuid.uuid7()

        authorship_with_whitespace = [
            AuthorshipFactory.build(
                display_name="  John Smith  ",
                orcid="0000-0000-0000-0001",
                position=destiny_sdk.enhancements.AuthorPosition.FIRST,
            ),
            AuthorshipFactory.build(
                display_name="Alice Johnson",
                orcid="0000-0000-0000-0002",
                position=destiny_sdk.enhancements.AuthorPosition.MIDDLE,
            ),
            AuthorshipFactory.build(
                display_name="Bob Williams",
                position=destiny_sdk.enhancements.AuthorPosition.LAST,
            ),
        ]

        biblio_enhancement_with_whitespace = EnhancementFactory.build(
            source="test_source",
            reference_id=canonical_reference_id,
            content=BibliographicMetadataEnhancementFactory.build(
                title="  Sample Research Paper  ",
                authorship=authorship_with_whitespace,
                publication_date=datetime(year=2023, month=4, day=2, tzinfo=UTC),
            ),
        )

        abstract_enhancement_with_whitespace = EnhancementFactory.build(
            source="test_source",
            reference_id=canonical_reference_id,
            content=AbstractContentEnhancementFactory.build(
                abstract="   Sample Reserch Abstract   "
            ),
        )

        reference_with_whitespace = ReferenceFactory.build(
            id=canonical_reference_id,
            enhancements=[
                biblio_enhancement_with_whitespace,
                abstract_enhancement_with_whitespace,
            ],
        )

        result = ReferenceSearchFieldsProjection.get_from_reference(
            reference_with_whitespace
        )
        assert result.title == "Sample Research Paper"  # Whitespace stripped
        assert result.publication_year == (
            biblio_enhancement_with_whitespace.content.publication_year
        )
        assert result.abstract == "Sample Reserch Abstract"  # Whitespace stripped
        assert len(result.authors) == 3
        # Check author ordering: first, middle (sorted by name), last
        assert result.authors[0] == "John Smith"  # Whitespace stripped
        assert result.authors[1] == "Alice Johnson"  # Middle author
        assert result.authors[2] == "Bob Williams"  # Last author

    def test_get_from_reference_publication_date_fallback(self):
        """Test we get year from publication date if publication year not provided."""
        enhancement_without_publication_year = EnhancementFactory.build(
            source="fallback_source",
            # Can't use factory here as we're explicity setting missing values
            content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                enhancement_type=EnhancementType.BIBLIOGRAPHIC,
                title="Date Fallback Paper",
                publication_date=date(2022, 8, 10),
                publication_year=None,
            ),
        )
        assert not enhancement_without_publication_year.content.publication_year

        reference = Reference(
            enhancements=[enhancement_without_publication_year],
        )

        result = ReferenceSearchFieldsProjection.get_from_reference(reference)
        assert result.publication_year == 2022  # From publication_date

    def test_get_from_reference_prioritises_annotations_by_scheme(self):
        """Test that we prioritise annotations by scheme, not by label."""
        reference_id = uuid.uuid7()

        annotation_enhancement_1 = EnhancementFactory.build(
            reference_id=reference_id,
            content=AnnotationEnhancementFactory.build(
                annotations=[
                    BooleanAnnotationFactory.build(
                        scheme="scheme1", label="label1", value=True
                    ),
                    BooleanAnnotationFactory.build(
                        scheme="scheme1", label="label2", value=True
                    ),
                    BooleanAnnotationFactory.build(
                        scheme="scheme2", label="label3", value=True
                    ),
                ]
            ),
            created_at=datetime(year=2021, month=2, day=17, tzinfo=UTC),
        )

        annotation_enhancement_2 = EnhancementFactory.build(
            reference_id=reference_id,
            content=AnnotationEnhancementFactory.build(
                annotations=[
                    BooleanAnnotationFactory.build(
                        scheme="scheme1", label="label1", value=False, score=0.9
                    ),
                ]
            ),
            # Created 1 day after the first annotation enhancement
            created_at=annotation_enhancement_1.created_at + timedelta(days=1),
        )

        reference = ReferenceFactory.build(
            id=reference_id,
            enhancements=[annotation_enhancement_1, annotation_enhancement_2],
        )

        result = ReferenceSearchFieldsProjection.get_from_reference(reference)
        # Should get scheme1 from annotation_enhancement_1
        # and scheme2 from annotation_enhancement_2
        assert set(result.annotations) == {"scheme2/label3"}
        assert set(result.evaluated_schemes) == {"scheme1", "scheme2"}

    def test_get_from_reference_empty_enhancements(self):
        """Test extracting reference search feilds with empty enhancements"""
        # Can't use factories here as we're explicity setting missing values
        # And the post generation will replace them.
        reference_empty = Reference(
            id=uuid.uuid7(),
            visibility=Visibility.PUBLIC,
            enhancements=[],
            identifiers=[],
        )

        result_empty = ReferenceSearchFieldsProjection.get_from_reference(
            reference_empty
        )
        assert result_empty.title is None
        assert result_empty.publication_year is None
        assert result_empty.authors == []
        assert result_empty.abstract is None

    def test_get_from_reference_none_enhancements(self):
        """Test extracting reference search fields with None enhancements."""
        # Can't use factories here as we're explicity setting missing values
        # And the post generation will replace them.
        reference_none = Reference(
            id=uuid.uuid7(),
            visibility=Visibility.PUBLIC,
            enhancements=None,
            identifiers=[],
        )

        result_none = ReferenceSearchFieldsProjection.get_from_reference(reference_none)
        assert result_none.title is None
        assert result_none.publication_year is None
        assert result_none.authors == []
        assert result_none.abstract is None

    def test_positive_boolean_annotations(self):
        annotations_by_scheme = {
            "scheme1": [
                BooleanAnnotationFactory.build(
                    scheme="scheme1", label="label1", value=True
                ),
                BooleanAnnotationFactory.build(
                    scheme="scheme1", label="label2", value=False
                ),
            ],
            "scheme2": [
                BooleanAnnotationFactory.build(
                    scheme="scheme2", label="label3", value=True
                ),
                ScoreAnnotationFactory.build(
                    scheme="scheme2", label="label4", score=0.55
                ),
            ],
        }

        result = ReferenceSearchFieldsProjection._ReferenceSearchFieldsProjection__positive_boolean_annotations(  # noqa: E501, SLF001
            annotations_by_scheme
        )
        assert result == {"scheme1/label1", "scheme2/label3"}

    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            (
                BooleanAnnotationFactory.build(
                    value=True,
                    score=0.7,
                    data={"inclusion_score": 0.42},
                ),
                0.42,
            ),
            (BooleanAnnotationFactory.build(value=True, score=0.8), 0.8),
            (BooleanAnnotationFactory.build(value=False, score=0.2), 0.8),
            (ScoreAnnotationFactory.build(score=0.55), 0.55),
            (BooleanAnnotationFactory.build(value=True, score=None), None),
        ],
    )
    def test_positive_annotation_score(self, annotation, expected):
        result = ReferenceSearchFieldsProjection._ReferenceSearchFieldsProjection__positive_annotation_score(  # noqa: E501, SLF001
            annotation
        )
        assert result == expected


class TestDeduplicatedReferenceProjection:
    """Test the DeduplicatedReferenceProjection class."""

    def test_get_from_reference_no_duplicates(self, complete_reference):
        """Test deduplication with no duplicate references."""
        complete_reference.duplicate_references = []

        result = DeduplicatedReferenceProjection.get_from_reference(complete_reference)

        # Should be identical to original except duplicate_references should be None
        assert result.id == complete_reference.id
        assert result.visibility == complete_reference.visibility
        assert len(result.enhancements) == len(complete_reference.enhancements)
        assert len(result.identifiers) == len(complete_reference.identifiers)
        assert result.duplicate_references is None

    def test_get_from_reference_with_duplicates(self, complete_reference):
        """Test deduplication with duplicate references."""
        # Create duplicate reference
        duplicate_enhancement = Enhancement(
            id=uuid.uuid7(),
            source="duplicate_source",
            visibility=Visibility.PUBLIC,
            content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                enhancement_type=EnhancementType.BIBLIOGRAPHIC,
                title="Duplicate Title",
            ),
            reference_id=uuid.uuid7(),
        )

        duplicate_identifier = LinkedExternalIdentifier(
            id=uuid.uuid7(),
            identifier=destiny_sdk.identifiers.DOIIdentifier(
                identifier="10.1000/duplicate",
                identifier_type=ExternalIdentifierType.DOI,
            ),
            reference_id=uuid.uuid7(),
        )

        duplicate_reference = Reference(
            id=uuid.uuid7(),
            visibility=Visibility.PUBLIC,
            enhancements=[duplicate_enhancement],
            identifiers=[duplicate_identifier],
            duplicate_references=[],  # No nested duplicates
        )

        complete_reference.duplicate_references = [duplicate_reference]

        result = DeduplicatedReferenceProjection.get_from_reference(complete_reference)

        # Should have original + duplicate enhancements and identifiers
        assert len(result.enhancements) == len(complete_reference.enhancements) + 1
        assert len(result.identifiers) == len(complete_reference.identifiers) + 1
        assert result.duplicate_references is None

        # Check that duplicate data is included
        enhancement_sources = [e.source for e in result.enhancements]
        assert "test_source" in enhancement_sources
        assert "duplicate_source" in enhancement_sources

        identifier_values = [i.identifier.identifier for i in result.identifiers]
        assert "10.1000/abc123" in identifier_values
        assert "10.1000/duplicate" in identifier_values

    def test_get_from_reference_none_duplicates_raises_error(self, complete_reference):
        """Test that None duplicate_references raises ProjectionError."""
        complete_reference.duplicate_references = None

        with pytest.raises(
            ProjectionError, match="Reference must have duplicates preloaded"
        ):
            DeduplicatedReferenceProjection.get_from_reference(complete_reference)

    def test_get_from_reference_none_enhancements_preserved(self):
        """Test that None enhancements are preserved (not preloaded)."""
        reference = Reference(
            id=uuid.uuid7(),
            visibility=Visibility.PUBLIC,
            enhancements=None,  # Not preloaded
            identifiers=[],
            duplicate_references=[],
        )

        result = DeduplicatedReferenceProjection.get_from_reference(reference)

        assert result.enhancements is None

    def test_get_from_reference_none_identifiers_preserved(self):
        """Test that None identifiers are preserved (not preloaded)."""
        reference = Reference(
            id=uuid.uuid7(),
            visibility=Visibility.PUBLIC,
            enhancements=[],
            identifiers=None,  # Not preloaded
            duplicate_references=[],
        )

        result = DeduplicatedReferenceProjection.get_from_reference(reference)

        assert result.identifiers is None

    def test_get_from_reference_recursive_duplicates(self, complete_reference):
        """Test deduplication with nested duplicate references."""
        # Create a nested duplicate
        nested_enhancement = Enhancement(
            id=uuid.uuid7(),
            source="nested_source",
            visibility=Visibility.PUBLIC,
            content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                enhancement_type=EnhancementType.BIBLIOGRAPHIC,
                title="Nested Title",
            ),
            reference_id=uuid.uuid7(),
        )

        nested_reference = Reference(
            id=uuid.uuid7(),
            visibility=Visibility.PUBLIC,
            enhancements=[nested_enhancement],
            identifiers=[],
            duplicate_references=[],  # End of chain
        )

        # Create intermediate duplicate with nested duplicate
        intermediate_enhancement = Enhancement(
            id=uuid.uuid7(),
            source="intermediate_source",
            visibility=Visibility.PUBLIC,
            content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                enhancement_type=EnhancementType.BIBLIOGRAPHIC,
                title="Intermediate Title",
            ),
            reference_id=uuid.uuid7(),
        )

        intermediate_reference = Reference(
            id=uuid.uuid7(),
            visibility=Visibility.PUBLIC,
            enhancements=[intermediate_enhancement],
            identifiers=[],
            duplicate_references=[nested_reference],
        )

        complete_reference.duplicate_references = [intermediate_reference]

        result = DeduplicatedReferenceProjection.get_from_reference(complete_reference)

        # Should have all enhancements from the chain
        enhancement_sources = [e.source for e in result.enhancements]
        assert "test_source" in enhancement_sources  # Original
        assert "intermediate_source" in enhancement_sources  # Intermediate
        assert "nested_source" in enhancement_sources  # Nested
        assert len(result.enhancements) == 7  # 5 original + 1 intermediate + 1 nested
