import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.references.models.models import (
    AbstractContentEnhancement,
    AbstractProcessType,
    Annotation,
    AnnotationEnhancement,
    BibliographicMetadataEnhancement,
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifierBase,
    ExternalIdentifierType,
    Location,
    LocationEnhancement,
    Reference,
    Visibility,
)


def test_bibliographic_metadata_enhancement_valid():
    # Create valid bibliographic content
    bibliographic = BibliographicMetadataEnhancement(
        enhancement_type=EnhancementType.BIBLIOGRAPHIC,
        authorship=[],
        cited_by_count=10,
        created_date=date(2020, 1, 1),
        publication_date=date(2020, 1, 2),
        publication_year=2020,
        publisher="Test Publisher",
        title="Test Title",
    )
    enhancement = Enhancement(
        source="test_source",
        visibility="public",
        processor_version="1.0",
        enhancement_type=EnhancementType.BIBLIOGRAPHIC,
        content=bibliographic,
        reference_id=uuid.uuid4(),
    )
    assert enhancement.content.enhancement_type == EnhancementType.BIBLIOGRAPHIC


def test_abstract_content_enhancement_valid():
    # Create valid abstract content
    abstract_content = AbstractContentEnhancement(
        enhancement_type=EnhancementType.ABSTRACT,
        process=AbstractProcessType.UNINVERTED,
        abstract="This is a test abstract.",
    )
    enhancement = Enhancement(
        source="test_source",
        visibility="public",
        processor_version="2.0",
        enhancement_type=EnhancementType.ABSTRACT,
        content=abstract_content,
        reference_id=uuid.uuid4(),
    )
    assert enhancement.content.abstract == "This is a test abstract."


def test_annotation_enhancement_valid():
    # Create valid annotation content
    annotation1 = Annotation(
        annotation_type="openalex:topic",
        label="Machine Learning",
        data={"confidence": 0.95},
    )
    annotations_content = AnnotationEnhancement(
        enhancement_type=EnhancementType.ANNOTATION, annotations=[annotation1]
    )
    enhancement = Enhancement(
        source="test_source",
        visibility="public",
        processor_version="1.5",
        enhancement_type=EnhancementType.ANNOTATION,
        content=annotations_content,
        reference_id=uuid.uuid4(),
    )
    assert enhancement.content.annotations[0].label == "Machine Learning"


def test_location_enhancement_valid():
    # Create valid location content
    location = Location(
        is_oa=True,
        version="publishedVersion",
        landing_page_url="https://example.com",
        pdf_url="https://example.com/doc.pdf",
        license="cc-by",
        extra={"note": "Accessible"},
    )
    location_content = LocationEnhancement(
        enhancement_type=EnhancementType.LOCATION, locations=[location]
    )
    enhancement = Enhancement(
        source="test_source",
        visibility="public",
        processor_version="1.2",
        enhancement_type=EnhancementType.LOCATION,
        content=location_content,
        reference_id=uuid.uuid4(),
    )
    assert enhancement.content.locations[0].license == "cc-by"


def test_mismatched_enhancement_type():
    # Intentionally create mismatch between parent enhancement_type and
    # content.enhancement_type
    bibliographic = BibliographicMetadataEnhancement(
        enhancement_type=EnhancementType.BIBLIOGRAPHIC,
        authorship=[],
        cited_by_count=5,
        created_date=date(2020, 5, 1),
        publication_date=date(2020, 5, 2),
        publication_year=2020,
        publisher="Mismatch Publisher",
    )
    with pytest.raises(ValidationError) as excinfo:
        Enhancement(
            source="test_source",
            visibility="public",
            processor_version="1.0",
            # expecting ABSTRACT but passed bibliographic content
            enhancement_type=EnhancementType.ABSTRACT,
            content=bibliographic,
            reference_id=uuid.uuid4(),
        )
    assert "content enhancement_type must match parent enhancement_type" in str(
        excinfo.value
    )


def test_valid_doi():
    obj = ExternalIdentifierBase(
        identifier_type=ExternalIdentifierType.DOI,
        identifier="10.1000/xyz123",
        other_identifier_name=None,
    )
    assert obj.identifier == "10.1000/xyz123"


def test_invalid_doi():
    with pytest.raises(ValueError, match="The provided DOI is not in a valid format."):
        ExternalIdentifierBase(
            identifier_type=ExternalIdentifierType.DOI,
            identifier="invalid_doi",
            other_identifier_name=None,
        )


def test_valid_pmid():
    obj = ExternalIdentifierBase(
        identifier_type=ExternalIdentifierType.PM_ID,
        identifier="123456",
        other_identifier_name=None,
    )
    assert obj.identifier == "123456"


def test_invalid_pmid():
    with pytest.raises(ValueError, match="PM ID must be an integer."):
        ExternalIdentifierBase(
            identifier_type=ExternalIdentifierType.PM_ID,
            identifier="abc123",
            other_identifier_name=None,
        )


def test_valid_open_alex():
    valid_openalex = "W123456789"
    obj = ExternalIdentifierBase(
        identifier_type=ExternalIdentifierType.OPEN_ALEX,
        identifier=valid_openalex,
        other_identifier_name=None,
    )
    assert obj.identifier == valid_openalex


def test_invalid_open_alex():
    with pytest.raises(
        ValueError, match="The provided OpenAlex ID is not in a valid format."
    ):
        ExternalIdentifierBase(
            identifier_type=ExternalIdentifierType.OPEN_ALEX,
            identifier="invalid-openalex",
            other_identifier_name=None,
        )


def test_valid_other_identifier():
    obj = ExternalIdentifierBase(
        identifier_type=ExternalIdentifierType.OTHER,
        identifier="custom_identifier",
        other_identifier_name="custom_type",
    )
    assert obj.other_identifier_name == "custom_type"


def test_invalid_other_identifier_missing_name():
    with pytest.raises(
        ValueError,
        match="other_identifier_name must be provided when identifier_type is 'other'",
    ):
        ExternalIdentifierBase(
            identifier_type=ExternalIdentifierType.OTHER,
            identifier="custom_identifier",
            other_identifier_name=None,
        )


def test_invalid_other_identifier_provided_when_not_other():
    with pytest.raises(
        ValueError,
        match="other_identifier_name must be empty when identifier_type is not 'other'",
    ):
        ExternalIdentifierBase(
            identifier_type=ExternalIdentifierType.DOI,
            identifier="10.1000/xyz123",
            other_identifier_name="unexpected",
        )


def test_enhancement_request_valid():
    enhancement_request = EnhancementRequest(
        reference_id=uuid.uuid4(),
        reference=Reference(visibility=Visibility.RESTRICTED),
        robot_id=uuid.uuid4(),
    )

    assert enhancement_request.request_status == EnhancementRequestStatus.RECEIVED
    assert enhancement_request.enhancement_parameters == {}
    assert enhancement_request.error is None
