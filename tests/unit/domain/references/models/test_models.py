import uuid
from datetime import date

import destiny_sdk
import pytest
from pydantic import ValidationError

from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifierAdapter,
    ExternalIdentifierType,
    Reference,
    Visibility,
)


def test_bibliographic_metadata_enhancement_valid():
    # Create valid bibliographic content
    bibliographic = destiny_sdk.enhancements.BibliographicMetadataEnhancement(
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
    abstract_content = destiny_sdk.enhancements.AbstractContentEnhancement(
        enhancement_type=EnhancementType.ABSTRACT,
        process=destiny_sdk.enhancements.AbstractProcessType.UNINVERTED,
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
    annotation1 = destiny_sdk.enhancements.Annotation(
        annotation_type="openalex:topic",
        label="Machine Learning",
        data={"confidence": 0.95},
    )
    annotations_content = destiny_sdk.enhancements.AnnotationEnhancement(
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
    location = destiny_sdk.enhancements.Location(
        is_oa=True,
        version="publishedVersion",
        landing_page_url="https://example.com",
        pdf_url="https://example.com/doc.pdf",
        license="cc-by",
        extra={"note": "Accessible"},
    )
    location_content = destiny_sdk.enhancements.LocationEnhancement(
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


def test_valid_doi():
    obj = ExternalIdentifierAdapter.validate_python(
        {
            "identifier_type": ExternalIdentifierType.DOI,
            "identifier": "10.1000/xyz123",
            "other_identifier_name": None,
        }
    )
    assert obj.identifier == "10.1000/xyz123"


def test_invalid_doi():
    with pytest.raises(ValidationError, match="String should match pattern"):
        ExternalIdentifierAdapter.validate_python(
            {
                "identifier_type": ExternalIdentifierType.DOI,
                "identifier": "invalid_doi",
                "other_identifier_name": None,
            }
        )


def test_valid_pmid():
    obj = ExternalIdentifierAdapter.validate_python(
        {
            "identifier_type": ExternalIdentifierType.PM_ID,
            "identifier": 123456,
            "other_identifier_name": None,
        }
    )
    assert obj.identifier == 123456


def test_invalid_pmid():
    with pytest.raises(ValidationError, match="Input should be a valid integer"):
        ExternalIdentifierAdapter.validate_python(
            {
                "identifier_type": ExternalIdentifierType.PM_ID,
                "identifier": "abc123",
                "other_identifier_name": None,
            }
        )


def test_valid_open_alex():
    valid_openalex = "W123456789"
    obj = ExternalIdentifierAdapter.validate_python(
        {
            "identifier_type": ExternalIdentifierType.OPEN_ALEX,
            "identifier": valid_openalex,
            "other_identifier_name": None,
        }
    )
    assert obj.identifier == valid_openalex


def test_invalid_open_alex():
    with pytest.raises(ValidationError, match="String should match pattern"):
        ExternalIdentifierAdapter.validate_python(
            {
                "identifier_type": ExternalIdentifierType.OPEN_ALEX,
                "identifier": "invalid-openalex",
                "other_identifier_name": None,
            }
        )


def test_valid_other_identifier():
    obj = ExternalIdentifierAdapter.validate_python(
        {
            "identifier_type": ExternalIdentifierType.OTHER,
            "identifier": "custom_identifier",
            "other_identifier_name": "custom_type",
        }
    )
    assert obj.other_identifier_name == "custom_type"


def test_invalid_other_identifier_missing_name():
    with pytest.raises(
        ValidationError,
        match="Field required",
    ):
        ExternalIdentifierAdapter.validate_python(
            {
                "identifier_type": ExternalIdentifierType.OTHER,
                "identifier": "custom_identifier",
            }
        )


def test_enhancement_request_valid():
    enhancement_request = EnhancementRequest(
        reference_id=uuid.uuid4(),
        reference=Reference(visibility=Visibility.RESTRICTED),
        robot_id=uuid.uuid4(),
    )

    assert enhancement_request.request_status == EnhancementRequestStatus.RECEIVED
    assert enhancement_request.enhancement_parameters is None
    assert enhancement_request.error is None
