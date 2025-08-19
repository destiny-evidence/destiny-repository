import uuid
from datetime import date

import destiny_sdk
import pytest
from pydantic import ValidationError


def test_bibliographic_metadata_enhancement_valid():
    # Create valid bibliographic content
    bibliographic = destiny_sdk.enhancements.BibliographicMetadataEnhancement(
        enhancement_type=destiny_sdk.enhancements.EnhancementType.BIBLIOGRAPHIC,
        authorship=[],
        cited_by_count=10,
        created_date=date(2020, 1, 1),
        publication_date=date(2050, 1, 2),
        publication_year=2020,
        publisher="Test Publisher",
        title="Test Title",
    )
    enhancement = destiny_sdk.enhancements.Enhancement(
        id=uuid.uuid4(),
        source="test_source",
        visibility="public",
        robot_version="1.0",
        enhancement_type=destiny_sdk.enhancements.EnhancementType.BIBLIOGRAPHIC,
        content=bibliographic,
        reference_id=uuid.uuid4(),
    )
    assert (
        enhancement.content.enhancement_type
        == destiny_sdk.enhancements.EnhancementType.BIBLIOGRAPHIC
    )


def test_abstract_content_enhancement_valid():
    # Create valid abstract content
    abstract_content = destiny_sdk.enhancements.AbstractContentEnhancement(
        enhancement_type=destiny_sdk.enhancements.EnhancementType.ABSTRACT,
        process=destiny_sdk.enhancements.AbstractProcessType.UNINVERTED,
        abstract="This is a test abstract.",
    )
    enhancement = destiny_sdk.enhancements.Enhancement(
        id=uuid.uuid4(),
        source="test_source",
        visibility="public",
        robot_version="2.0",
        enhancement_type=destiny_sdk.enhancements.EnhancementType.ABSTRACT,
        content=abstract_content,
        reference_id=uuid.uuid4(),
    )
    assert enhancement.content.abstract == "This is a test abstract."


def test_annotation_enhancement_valid():
    # Create valid annotation content
    annotation1 = destiny_sdk.enhancements.BooleanAnnotation(
        annotation_type=destiny_sdk.enhancements.AnnotationType.BOOLEAN,
        scheme="openalex:topic",
        value=True,
        label="Machine Learning",
        score=0.95,
        data={"confidence": 0.95},
    )
    annotations_content = destiny_sdk.enhancements.AnnotationEnhancement(
        enhancement_type=destiny_sdk.enhancements.EnhancementType.ANNOTATION,
        annotations=[annotation1],
    )
    enhancement = destiny_sdk.enhancements.Enhancement(
        id=uuid.uuid4(),
        source="test_source",
        visibility="public",
        robot_version="1.5",
        enhancement_type=destiny_sdk.enhancements.EnhancementType.ANNOTATION,
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
        enhancement_type=destiny_sdk.enhancements.EnhancementType.LOCATION,
        locations=[location],
    )
    enhancement = destiny_sdk.enhancements.Enhancement(
        id=uuid.uuid4(),
        source="test_source",
        visibility="public",
        robot_version="1.2",
        enhancement_type=destiny_sdk.enhancements.EnhancementType.LOCATION,
        content=location_content,
        reference_id=uuid.uuid4(),
    )
    assert enhancement.content.locations[0].license == "cc-by"


def test_empty_annotation_enhancement_errors():
    # Test that an empty annotations list raises a validation error
    with pytest.raises(
        ValidationError, match="List should have at least 1 item after validation"
    ):
        destiny_sdk.enhancements.AnnotationEnhancement(
            enhancement_type=destiny_sdk.enhancements.EnhancementType.ANNOTATION,
            annotations=[],
        )


def test_empty_location_enhancement_errors():
    # Test that an empty locations list raises a validation error
    with pytest.raises(
        ValidationError, match="List should have at least 1 item after validation"
    ):
        destiny_sdk.enhancements.LocationEnhancement(
            enhancement_type=destiny_sdk.enhancements.EnhancementType.LOCATION,
            locations=[],
        )
