"""Unit tests for the projection functions in the references module."""

import uuid
from datetime import date

import destiny_sdk
import pytest

from app.core.exceptions import ProjectionError
from app.domain.references.models.models import (
    Enhancement,
    EnhancementType,
    ExternalIdentifierType,
    Fingerprint,
    LinkedExternalIdentifier,
    Reference,
    Visibility,
)
from app.domain.references.models.projections import (
    CandidacyFingerprintProjection,
    DeduplicatedReferenceProjection,
    FingerprintProjection,
)


@pytest.fixture
def sample_authorship():
    """Create sample authorship data."""
    return [
        destiny_sdk.enhancements.Authorship(
            display_name="John Smith",
            orcid="0000-0000-0000-0001",
            position=destiny_sdk.enhancements.AuthorPosition.FIRST,
        ),
        destiny_sdk.enhancements.Authorship(
            display_name="Alice Johnson",
            orcid="0000-0000-0000-0002",
            position=destiny_sdk.enhancements.AuthorPosition.MIDDLE,
        ),
        destiny_sdk.enhancements.Authorship(
            display_name="Bob Williams",
            orcid=None,
            position=destiny_sdk.enhancements.AuthorPosition.LAST,
        ),
    ]


@pytest.fixture
def bibliographic_enhancement(sample_authorship):
    """Create a bibliographic enhancement."""
    content = destiny_sdk.enhancements.BibliographicMetadataEnhancement(
        enhancement_type=EnhancementType.BIBLIOGRAPHIC,
        title="Sample Research Paper",
        authorship=sample_authorship,
        publication_year=2023,
        publication_date=date(2023, 5, 15),
        publisher="Academic Press",
        cited_by_count=42,
    )

    return Enhancement(
        id=uuid.uuid4(),
        source="test_source",
        visibility=Visibility.PUBLIC,
        robot_version="1.0.0",
        content=content,
        reference_id=uuid.uuid4(),
    )


@pytest.fixture
def abstract_enhancement():
    """Create an abstract enhancement."""
    content = destiny_sdk.enhancements.AbstractContentEnhancement(
        enhancement_type=EnhancementType.ABSTRACT,
        process=destiny_sdk.enhancements.AbstractProcessType.UNINVERTED,
        abstract="This is a sample abstract for testing purposes.",
    )

    return Enhancement(
        id=uuid.uuid4(),
        source="test_source",
        visibility=Visibility.PUBLIC,
        content=content,
        reference_id=uuid.uuid4(),
    )


@pytest.fixture
def doi_identifier():
    """Create a DOI identifier."""
    identifier = destiny_sdk.identifiers.DOIIdentifier(
        identifier="10.1000/abc123",
        identifier_type=ExternalIdentifierType.DOI,
    )
    return LinkedExternalIdentifier(
        id=uuid.uuid4(),
        identifier=identifier,
        reference_id=uuid.uuid4(),
    )


@pytest.fixture
def pubmed_identifier():
    """Create a PubMed identifier."""
    identifier = destiny_sdk.identifiers.PubMedIdentifier(
        identifier=12345678,
        identifier_type=ExternalIdentifierType.PM_ID,
    )
    return LinkedExternalIdentifier(
        id=uuid.uuid4(),
        identifier=identifier,
        reference_id=uuid.uuid4(),
    )


@pytest.fixture
def openalex_identifier():
    """Create an OpenAlex identifier."""
    identifier = destiny_sdk.identifiers.OpenAlexIdentifier(
        identifier="W1234567890",
        identifier_type=ExternalIdentifierType.OPEN_ALEX,
    )
    return LinkedExternalIdentifier(
        id=uuid.uuid4(),
        identifier=identifier,
        reference_id=uuid.uuid4(),
    )


@pytest.fixture
def other_identifier():
    """Create an other identifier."""
    identifier = destiny_sdk.identifiers.OtherIdentifier(
        identifier="978-0123456789",
        identifier_type=ExternalIdentifierType.OTHER,
        other_identifier_name="ISBN",
    )
    return LinkedExternalIdentifier(
        id=uuid.uuid4(),
        identifier=identifier,
        reference_id=uuid.uuid4(),
    )


@pytest.fixture
def reference_with_enhancements(bibliographic_enhancement, abstract_enhancement):
    """Create a reference with enhancements."""
    return Reference(
        id=uuid.uuid4(),
        visibility=Visibility.PUBLIC,
        enhancements=[bibliographic_enhancement, abstract_enhancement],
        identifiers=[],
    )


@pytest.fixture
def reference_with_identifiers(
    doi_identifier, pubmed_identifier, openalex_identifier, other_identifier
):
    """Create a reference with identifiers."""
    return Reference(
        id=uuid.uuid4(),
        visibility=Visibility.PUBLIC,
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

    return Reference(
        id=ref_id,
        visibility=Visibility.PUBLIC,
        enhancements=[bibliographic_enhancement, abstract_enhancement],
        identifiers=[doi_identifier, pubmed_identifier],
    )


class TestCandidacyFingerprintProjection:
    """Test the CandidacyFingerprintProjection class."""

    def test_get_from_reference(self, sample_authorship):
        """Test extracting candidacy fingerprint with various scenarios."""
        # Test 1: Complete bibliographic enhancement with author ordering and whitespace
        authorship_with_whitespace = [
            destiny_sdk.enhancements.Authorship(
                display_name="  John Smith  ",  # Test whitespace stripping
                orcid="0000-0000-0000-0001",
                position=destiny_sdk.enhancements.AuthorPosition.FIRST,
            ),
            destiny_sdk.enhancements.Authorship(
                display_name="Alice Johnson",
                orcid="0000-0000-0000-0002",
                position=destiny_sdk.enhancements.AuthorPosition.MIDDLE,
            ),
            destiny_sdk.enhancements.Authorship(
                display_name="Bob Williams",
                position=destiny_sdk.enhancements.AuthorPosition.LAST,
            ),
        ]

        content1 = destiny_sdk.enhancements.BibliographicMetadataEnhancement(
            enhancement_type=EnhancementType.BIBLIOGRAPHIC,
            title="  Sample Research Paper  ",  # Test title whitespace stripping
            authorship=authorship_with_whitespace,
            publication_year=2023,
            publication_date=date(2023, 5, 15),
            publisher="Academic Press",
        )

        enhancement1 = Enhancement(
            id=uuid.uuid4(),
            source="test_source",
            visibility=Visibility.PUBLIC,
            content=content1,
            reference_id=uuid.uuid4(),
        )

        # Test 2: Publication date fallback when publication_year is None
        content2 = destiny_sdk.enhancements.BibliographicMetadataEnhancement(
            enhancement_type=EnhancementType.BIBLIOGRAPHIC,
            title="Date Fallback Paper",
            publication_date=date(2022, 8, 10),
            # No publication_year specified - should fall back to date.year
        )

        enhancement2 = Enhancement(
            id=uuid.uuid4(),
            source="fallback_source",
            visibility=Visibility.PUBLIC,
            content=content2,
            reference_id=uuid.uuid4(),
        )

        # Test 3: Multiple enhancements with hydration behavior
        content3 = destiny_sdk.enhancements.BibliographicMetadataEnhancement(
            enhancement_type=EnhancementType.BIBLIOGRAPHIC,
            title="Hydration Title",  # This should be used
        )

        enhancement3 = Enhancement(
            id=uuid.uuid4(),
            source="hydration_source1",
            visibility=Visibility.PUBLIC,
            content=content3,
            reference_id=uuid.uuid4(),
        )

        content4 = destiny_sdk.enhancements.BibliographicMetadataEnhancement(
            enhancement_type=EnhancementType.BIBLIOGRAPHIC,
            # No title - should use previous one
            authorship=sample_authorship,  # Should use this authorship
            publication_year=2024,  # Should use this year
        )

        enhancement4 = Enhancement(
            id=uuid.uuid4(),
            source="hydration_source2",
            visibility=Visibility.PUBLIC,
            content=content4,
            reference_id=uuid.uuid4(),
        )

        # Test complete enhancement
        reference1 = Reference(
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=[enhancement1],
            identifiers=[],
        )

        result1 = CandidacyFingerprintProjection.get_from_reference(reference1)
        assert result1.title == "Sample Research Paper"  # Whitespace stripped
        assert result1.publication_year == 2023
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

        result2 = CandidacyFingerprintProjection.get_from_reference(reference2)
        assert result2.publication_year == 2022  # From publication_date

        # Test multiple enhancements hydration
        reference3 = Reference(
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=[enhancement3, enhancement4],
            identifiers=[],
        )

        result3 = CandidacyFingerprintProjection.get_from_reference(reference3)
        assert result3.title == "Hydration Title"  # From first enhancement
        assert result3.publication_year == 2024  # From second enhancement
        assert len(result3.authors) == 3  # From second enhancement

    def test_get_from_reference_empty_and_none_enhancements(self):
        """Test extracting candidacy fingerprint with no or None enhancements."""
        # Test with empty enhancements list
        reference_empty = Reference(
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=[],
            identifiers=[],
        )

        result_empty = CandidacyFingerprintProjection.get_from_reference(
            reference_empty
        )
        assert result_empty.title is None
        assert result_empty.publication_year is None
        assert result_empty.authors == []
        assert not result_empty.searchable

        # Test with None enhancements
        reference_none = Reference(
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=None,
            identifiers=[],
        )

        result_none = CandidacyFingerprintProjection.get_from_reference(reference_none)
        assert result_none.title is None
        assert result_none.publication_year is None
        assert result_none.authors == []
        assert not result_none.searchable

    def test_get_from_fingerprint(self):
        """Test getting candidacy fingerprint from full fingerprint."""
        fingerprint = Fingerprint(
            title="Test Title",
            authors=["Author One", "Author Two"],
            publication_year=2023,
            doi_identifier="10.1000/test",
            pubmed_identifier="12345",
            publisher="Test Publisher",
        )

        result = CandidacyFingerprintProjection.get_from_fingerprint(fingerprint)
        assert result.title == "Test Title"
        assert result.authors == ["Author One", "Author Two"]
        assert result.publication_year == 2023
        # Should not include extra fields from Fingerprint
        assert not hasattr(result, "doi_identifier")
        assert not hasattr(result, "publisher")


class TestFingerprintProjection:
    """Test the FingerprintProjection class."""

    def test_get_from_reference(
        self,
        complete_reference,
        reference_with_identifiers,
        reference_with_enhancements,
    ):
        """Test extracting full fingerprint from various reference types."""
        # Test 1: Complete reference with all data types
        result_complete = FingerprintProjection.get_from_reference(complete_reference)

        # Candidacy fingerprint fields
        assert result_complete.title == "Sample Research Paper"
        assert result_complete.publication_year == 2023
        assert len(result_complete.authors) == 3

        # Identifier fields
        assert result_complete.doi_identifier == "10.1000/abc123"
        assert result_complete.pubmed_identifier == 12345678

        # Enhancement fields
        assert result_complete.publisher == "Academic Press"
        assert (
            result_complete.abstract
            == "This is a sample abstract for testing purposes."
        )

        # Test 2: Identifiers only
        result_ids = FingerprintProjection.get_from_reference(
            reference_with_identifiers
        )

        assert result_ids.doi_identifier == "10.1000/abc123"
        assert result_ids.pubmed_identifier == 12345678
        assert result_ids.openalex_identifier == "W1234567890"
        assert result_ids.other_identifiers == {"ISBN": "978-0123456789"}

        # Should have None/empty values for missing data
        assert result_ids.title is None
        assert result_ids.publisher is None
        assert result_ids.abstract is None

        # Test 3: Enhancements only
        result_enhancements = FingerprintProjection.get_from_reference(
            reference_with_enhancements
        )

        assert result_enhancements.title == "Sample Research Paper"
        assert result_enhancements.publisher == "Academic Press"
        assert (
            result_enhancements.abstract
            == "This is a sample abstract for testing purposes."
        )

        # Should have None values for missing identifiers
        assert result_enhancements.doi_identifier is None
        assert result_enhancements.pubmed_identifier is None
        assert result_enhancements.openalex_identifier is None
        assert result_enhancements.other_identifiers == {}

    def test_get_from_reference_empty(self):
        """Test extracting fingerprint from reference with no data."""
        reference = Reference(
            id=uuid.uuid4(),
            visibility=Visibility.PUBLIC,
            enhancements=[],
            identifiers=[],
        )

        result = FingerprintProjection.get_from_reference(reference)

        assert result.title is None
        assert result.authors == []
        assert result.publication_year is None
        assert result.doi_identifier is None
        assert result.pubmed_identifier is None
        assert result.openalex_identifier is None
        assert result.other_identifiers == {}
        assert result.publisher is None
        assert result.abstract is None


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
