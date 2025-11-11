"""Unit tests for the projection functions in the references module."""

import uuid
from datetime import UTC, date, datetime, timedelta

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
    AuthorshipFactory,
    BibliographicMetadataEnhancementFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    OpenAlexIdentifierFactory,
    OtherIdentifierFactory,
    PubMedIdentifierFactory,
    ReferenceFactory,
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
def doi_identifier():
    """Create a DOI identifier."""
    return LinkedExternalIdentifierFactory.build(
        identifier=DOIIdentifierFactory.build(identifier="10.1000/abc123")
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
    ref_id = uuid.uuid4()

    bibliographic_enhancement.reference_id = ref_id
    abstract_enhancement.reference_id = ref_id

    return ReferenceFactory.build(
        id=ref_id,
        enhancements=[bibliographic_enhancement, abstract_enhancement],
        identifiers=[],
    )


@pytest.fixture
def reference_with_identifiers(
    doi_identifier, pubmed_identifier, openalex_identifier, other_identifier
):
    """Create a reference with identifiers."""
    ref_id = uuid.uuid4()

    doi_identifier.reference_id = ref_id
    pubmed_identifier.reference_id = ref_id
    openalex_identifier.reference_id = ref_id
    other_identifier.reference_id = ref_id

    return ReferenceFactory.build(
        id=ref_id,
        enhancements=[],
        identifiers=[
            doi_identifier,
            pubmed_identifier,
            openalex_identifier,
            other_identifier,
        ],
    )


@pytest.fixture
def complete_reference(
    bibliographic_enhancement, abstract_enhancement, doi_identifier, pubmed_identifier
):
    """Create a reference with both enhancements and identifiers."""
    ref_id = uuid.uuid4()

    # Update enhancement reference IDs to match
    bibliographic_enhancement.reference_id = ref_id
    abstract_enhancement.reference_id = ref_id
    doi_identifier.reference_id = ref_id
    pubmed_identifier.reference_id = ref_id

    return ReferenceFactory.build(
        id=ref_id,
        enhancements=[bibliographic_enhancement, abstract_enhancement],
        identifiers=[doi_identifier, pubmed_identifier],
    )


class TestReferenceSearchFieldsProjection:
    """Test the ReferenceSearchFieldsProjection class."""

    def test_reference_sorting_prioritises_canonical(
        self, bibliographic_enhancement, sample_authorship
    ):
        """Test that we prioritise canonical enhancements"""
        reference_id = uuid.uuid4()

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
        reference_id = uuid.uuid4()

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
        reference_id = uuid.uuid4()
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

    def test_get_from_reference(self, sample_authorship, abstract_enhancement):
        """Test extracting candidacy fingerprint with various scenarios."""
        # Test 1: Complete bibliographic enhancement with author ordering and whitespace
        authorship_with_whitespace = [
            AuthorshipFactory.build(
                display_name="  John Smith  ",  # Test whitespace stripping
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

        content0 = BibliographicMetadataEnhancementFactory.build(
            title="Check we don't get this title! This should have a lower priority in "
            " the projection because it comes from a duplicate.",
            authorship=sample_authorship,
            publication_date=datetime(year=2021, month=2, day=17, tzinfo=UTC),
        )

        content1 = BibliographicMetadataEnhancementFactory.build(
            title="  Sample Research Paper  ",  # Test title whitespace stripping
            authorship=authorship_with_whitespace,
            publication_date=datetime(year=2023, month=4, day=2, tzinfo=UTC),
        )

        enhancement0 = EnhancementFactory.build(
            source="duplicate_source",
            content=content0,
        )

        enhancement1 = EnhancementFactory.build(
            source="test_source",
            content=content1,
        )

        # Test 2: Publication date fallback when publication_year is None
        content2 = BibliographicMetadataEnhancementFactory.build(
            enhancement_type=EnhancementType.BIBLIOGRAPHIC,
            title="Date Fallback Paper",
            publication_date=date(2022, 8, 10),
            publication_year=None,
        )

        enhancement2 = EnhancementFactory.build(
            source="fallback_source",
            content=content2,
        )

        # Test 3: Multiple enhancements with hydration behavior
        content3 = BibliographicMetadataEnhancementFactory.build(
            title="Hydration Title",  # This should be used
            authorship=[],
            publication_date=None,
        )

        enhancement3 = EnhancementFactory.build(
            source="hydration_source1",
            content=content3,
            created_at=datetime(year=2021, month=2, day=17, tzinfo=UTC),
        )

        content4 = BibliographicMetadataEnhancementFactory.build(
            # No title - should use previous one
            title=None,
            authorship=sample_authorship,  # Should use this authorship
        )

        enhancement4 = EnhancementFactory.build(
            source="hydration_source2",
            content=content4,
            created_at=datetime(year=2022, month=2, day=17, tzinfo=UTC),
        )

        # Test complete enhancement
        abstract_enhancement.reference_id = enhancement1.reference_id
        reference1 = ReferenceFactory.build(
            id=enhancement1.reference_id,
            enhancements=[enhancement0, enhancement1, abstract_enhancement],
            identifiers=[],
        )

        result1 = ReferenceSearchFieldsProjection.get_from_reference(reference1)
        assert result1.title == "Sample Research Paper"  # Whitespace stripped
        assert result1.publication_year == 2023
        assert result1.abstract == abstract_enhancement.content.abstract
        assert len(result1.authors) == 3
        # Check author ordering: first, middle (sorted by name), last
        assert result1.authors[0] == "John Smith"  # Whitespace stripped
        assert result1.authors[1] == "Alice Johnson"  # Middle author
        assert result1.authors[2] == "Bob Williams"  # Last author

        # Test publication date fallback
        reference2 = Reference(
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=[enhancement2],
            identifiers=[],
        )

        result2 = ReferenceSearchFieldsProjection.get_from_reference(reference2)
        assert result2.publication_year == 2022  # From publication_date

        # Test multiple enhancements hydration
        reference3 = Reference(
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=[enhancement3, enhancement4],
            identifiers=[],
        )

        result3 = ReferenceSearchFieldsProjection.get_from_reference(reference3)
        assert result3.title == enhancement3.content.title
        assert result3.publication_year == enhancement4.content.publication_year
        assert len(result3.authors) == len(enhancement4.content.authorship)

    def test_get_from_reference_empty_enhancements(self):
        """Test extracting reference search feilds with empty enhancements"""
        # Can't use factories here as we're explicity setting missing values
        # And the post generation will replace them.
        reference_empty = Reference(
            id=uuid.uuid4(),
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
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=None,
            identifiers=[],
        )

        result_none = ReferenceSearchFieldsProjection.get_from_reference(reference_none)
        assert result_none.title is None
        assert result_none.publication_year is None
        assert result_none.authors == []
        assert result_none.abstract is None


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
            id=uuid.uuid4(),
            source="duplicate_source",
            visibility=Visibility.PUBLIC,
            content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                enhancement_type=EnhancementType.BIBLIOGRAPHIC,
                title="Duplicate Title",
            ),
            reference_id=uuid.uuid4(),
        )

        duplicate_identifier = LinkedExternalIdentifier(
            id=uuid.uuid4(),
            identifier=destiny_sdk.identifiers.DOIIdentifier(
                identifier="10.1000/duplicate",
                identifier_type=ExternalIdentifierType.DOI,
            ),
            reference_id=uuid.uuid4(),
        )

        duplicate_reference = Reference(
            id=uuid.uuid4(),
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
            id=uuid.uuid4(),
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
            id=uuid.uuid4(),
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
            id=uuid.uuid4(),
            source="nested_source",
            visibility=Visibility.PUBLIC,
            content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                enhancement_type=EnhancementType.BIBLIOGRAPHIC,
                title="Nested Title",
            ),
            reference_id=uuid.uuid4(),
        )

        nested_reference = Reference(
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=[nested_enhancement],
            identifiers=[],
            duplicate_references=[],  # End of chain
        )

        # Create intermediate duplicate with nested duplicate
        intermediate_enhancement = Enhancement(
            id=uuid.uuid4(),
            source="intermediate_source",
            visibility=Visibility.PUBLIC,
            content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                enhancement_type=EnhancementType.BIBLIOGRAPHIC,
                title="Intermediate Title",
            ),
            reference_id=uuid.uuid4(),
        )

        intermediate_reference = Reference(
            id=uuid.uuid4(),
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
        assert len(result.enhancements) == 4  # 2 original + 1 intermediate + 1 nested
