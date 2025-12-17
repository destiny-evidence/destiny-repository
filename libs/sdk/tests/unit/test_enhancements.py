import datetime
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
        updated_date=date(2024, 1, 1),
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


def test_raw_enhancement_valid():
    raw = destiny_sdk.enhancements.RawEnhancement(
        source_export_date=datetime.datetime.now(tz=datetime.UTC),
        description="test data",
        metadata={"this": "is", "metadata": 0},
        data={"this": "is", "data": "stuff"},
    )

    assert raw.enhancement_type == destiny_sdk.enhancements.EnhancementType.RAW
    assert len(raw.model_dump(mode="json")) == 5  # Includes enhancement type
    assert raw.data.get("this") == "is"


def test_raw_enhancement_valid_data_is_a_string():
    raw = destiny_sdk.enhancements.RawEnhancement(
        source_export_date=datetime.datetime.now(tz=datetime.UTC),
        description="test data",
        metadata={"this": "is", "metadata": 0},
        data="I can make a sentence here",
    )

    assert len(raw.model_dump(mode="json")) == 5  # Includes enhancement type
    assert isinstance(raw.data, str)


def test_raw_enhancement_raise_error_if_empty_data():
    with pytest.raises(
        ValidationError, match="data must be populated on a raw enhancement"
    ):
        destiny_sdk.enhancements.RawEnhancement(
            source_export_date=datetime.datetime.now(tz=datetime.UTC),
            description="test data",
            metadata={"this": "is", "metadata": 0},
            data=None,
        )

    with pytest.raises(
        ValidationError, match="data must be populated on a raw enhancement"
    ):
        destiny_sdk.enhancements.RawEnhancement(
            source_export_date=datetime.datetime.now(tz=datetime.UTC),
            description="test data",
            metadata={"this": "is", "metadata": 0},
            data={},
        )


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


def test_association_enhancement_valid():
    # Create valid association content
    association_content = destiny_sdk.enhancements.ReferenceAssociationEnhancement(
        enhancement_type=destiny_sdk.enhancements.EnhancementType.REFERENCE_ASSOCIATION,
        associated_reference_ids=[
            uuid.uuid4(),
            destiny_sdk.identifiers.OpenAlexIdentifier(
                identifier="https://openalex.org/W1234567890",
                identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.OPEN_ALEX,
            ),
        ],
        association_type=destiny_sdk.enhancements.ReferenceAssociationType.CITES,
    )
    enhancement = destiny_sdk.enhancements.Enhancement(
        id=uuid.uuid4(),
        source="test_source",
        visibility="public",
        robot_version="1.0",
        enhancement_type=destiny_sdk.enhancements.EnhancementType.REFERENCE_ASSOCIATION,
        content=association_content,
        reference_id=uuid.uuid4(),
    )
    assert (
        enhancement.content.association_type
        == destiny_sdk.enhancements.ReferenceAssociationType.CITES
    )
    assert enhancement.content.associated_reference_ids[1].identifier == "W1234567890"


def test_association_enhancement_empty_associated_reference_ids_errors():
    # Test that an empty associated_reference_ids list raises a validation error
    with pytest.raises(ValidationError):
        destiny_sdk.enhancements.ReferenceAssociationEnhancement(
            enhancement_type=destiny_sdk.enhancements.EnhancementType.REFERENCE_ASSOCIATION,
            associated_reference_ids=[],
            association_type=destiny_sdk.enhancements.ReferenceAssociationType.CITES,
        )


def test_association_enhancement_invalid_identifier_type_errors():
    # Test that an invalid identifier type raises a validation error
    with pytest.raises(ValidationError):
        destiny_sdk.enhancements.ReferenceAssociationEnhancement(
            enhancement_type=destiny_sdk.enhancements.EnhancementType.REFERENCE_ASSOCIATION,
            associated_reference_ids=[
                "random-string",
            ],
            association_type=destiny_sdk.enhancements.ReferenceAssociationType.CITES,
        )
