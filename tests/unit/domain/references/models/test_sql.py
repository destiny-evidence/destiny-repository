import uuid

import destiny_sdk
import pytest

from app.domain.references.models.models import (
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifierType,
    Visibility,
)
from app.domain.references.models.sql import (
    Enhancement,
    EnhancementRequest,
    ExternalIdentifier,
    Reference,
)

# Dummy domain objects for testing conversion


class DummyDomainReference:
    def __init__(
        self,
        id,
        visibility,
        identifiers=None,
        enhancements=None,
        canonical_reference=None,
        duplicate_references=None,
    ):
        self.id = id
        self.visibility = visibility
        self.identifiers = identifiers
        self.enhancements = enhancements
        self.canonical_reference = canonical_reference
        self.duplicate_references = duplicate_references


class DummyExternalIdentifier:
    def __init__(self, identifier_type, identifier, other_identifier_name=None):
        self.identifier_type = identifier_type
        self.identifier = identifier
        self.other_identifier_name = other_identifier_name


class DummyDomainExternalIdentifier:
    def __init__(
        self, id, reference_id, identifier_type, identifier, other_identifier_name=None
    ):
        self.id = id
        self.reference_id = reference_id
        self.identifier = DummyExternalIdentifier(
            identifier_type=identifier_type,
            identifier=identifier,
            other_identifier_name=other_identifier_name,
        )
        # For preload test on ExternalIdentifier.to_domain
        self.reference = None


class DummyContent:
    def __init__(self):
        self.enhancement_type = EnhancementType.ANNOTATION

    def model_dump(self, mode="json"):
        return {
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "openalex:topic",
                    "value": True,
                    "label": "test_label",
                    "data": {"foo": "bar"},
                }
            ],
        }


class DummyDomainEnhancement:
    def __init__(
        self,
        id,
        reference_id,
        source,
        visibility,
        robot_version,
        content,
        derived_from=None,
    ):
        self.id = id
        self.reference_id = reference_id
        self.source = source
        self.visibility = visibility
        self.robot_version = robot_version
        self.derived_from = derived_from
        self.content = content
        # For preload test on Enhancement.to_domain
        self.reference = None


class DummyDomainEnhancementRequest:
    def __init__(
        self,
        id,
        reference_id,
        robot_id,
        request_status,
        enhancement_parameters,
        source=None,
        error=None,
    ):
        self.id = id
        self.reference_id = reference_id
        self.robot_id = robot_id
        self.request_status = request_status
        self.enhancement_parameters = enhancement_parameters
        self.source = source
        self.error = error


@pytest.mark.asyncio
async def test_reference_from_and_to_domain_without_preload():
    # Create dummy domain reference without identifiers and enhancements
    ref_id = uuid.uuid4()
    dummy_ref = DummyDomainReference(id=ref_id, visibility=Visibility.PUBLIC)

    # Convert from domain to SQL model
    sql_ref = Reference.from_domain(dummy_ref)
    assert sql_ref.id == dummy_ref.id
    assert sql_ref.visibility == dummy_ref.visibility

    # When no preload is requested, to_domain should yield None for relationships
    domain_ref = sql_ref.to_domain(preload=[])
    assert domain_ref.id == dummy_ref.id
    assert domain_ref.visibility == dummy_ref.visibility
    assert domain_ref.identifiers is None
    assert domain_ref.enhancements is None


@pytest.mark.asyncio
async def test_external_identifier_from_and_to_domain():
    # Create dummy domain external identifier
    ext_id = uuid.uuid4()
    ref_id = uuid.uuid4()
    dummy_ext = DummyDomainExternalIdentifier(
        id=ext_id,
        reference_id=ref_id,
        identifier_type=ExternalIdentifierType.DOI,
        identifier="10.1000/xyz123",
        other_identifier_name="",
    )

    # Convert from domain to SQL model
    sql_ext = ExternalIdentifier.from_domain(dummy_ext)
    assert sql_ext.id == dummy_ext.id
    assert sql_ext.reference_id == dummy_ext.reference_id
    assert sql_ext.identifier_type == dummy_ext.identifier.identifier_type
    assert sql_ext.identifier == dummy_ext.identifier.identifier

    # For preload test, assign a dummy SQL Reference to the relationship
    dummy_sql_ref = Reference(id=ref_id, visibility=Visibility.RESTRICTED)
    sql_ext.reference = dummy_sql_ref

    # Convert back to domain with preload reference
    domain_ext = sql_ext.to_domain(preload=["reference"])
    assert domain_ext.id == dummy_ext.id
    assert domain_ext.reference_id == dummy_ext.reference_id
    assert domain_ext.identifier.identifier_type == dummy_ext.identifier.identifier_type
    assert domain_ext.identifier.identifier == dummy_ext.identifier.identifier
    # Verify that the preloaded reference has the same id and visibility
    assert domain_ext.reference.id == dummy_sql_ref.id
    assert domain_ext.reference.visibility == dummy_sql_ref.visibility


@pytest.mark.asyncio
async def test_enhancement_from_and_to_domain():
    # Create dummy domain enhancement with content using DummyContent
    enh_id = uuid.uuid4()
    ref_id = uuid.uuid4()
    dummy_content = DummyContent()
    dummy_enh = DummyDomainEnhancement(
        id=enh_id,
        reference_id=ref_id,
        source="test_source",
        visibility=Visibility.PUBLIC,
        robot_version="1.0.0",
        content=dummy_content,
    )

    # Convert from domain to SQL model
    sql_enh = Enhancement.from_domain(dummy_enh)
    assert sql_enh.id == dummy_enh.id
    assert sql_enh.reference_id == dummy_enh.reference_id
    assert sql_enh.enhancement_type == dummy_enh.content.enhancement_type
    assert sql_enh.source == dummy_enh.source
    assert sql_enh.visibility == dummy_enh.visibility
    assert sql_enh.robot_version == dummy_enh.robot_version
    # Verify that content was dumped to JSON string correctly
    dumped = dummy_content.model_dump(mode="json")
    assert sql_enh.content == dumped

    # For preload test, assign a dummy SQL Reference to the relationship
    dummy_sql_ref = Reference(id=ref_id, visibility=Visibility.HIDDEN)
    sql_enh.reference = dummy_sql_ref

    # Convert back to domain with preload reference
    domain_enh = sql_enh.to_domain(preload=["reference"])
    assert domain_enh.id == dummy_enh.id
    assert domain_enh.reference_id == dummy_enh.reference_id
    assert domain_enh.content.enhancement_type == dummy_enh.content.enhancement_type
    assert domain_enh.source == dummy_enh.source
    assert domain_enh.visibility == dummy_enh.visibility
    assert domain_enh.robot_version == dummy_enh.robot_version
    # Verify that content was loaded correctly
    assert domain_enh.content == destiny_sdk.enhancements.AnnotationEnhancement(
        **sql_enh.content
    )
    # Verify that the preloaded reference was converted
    assert domain_enh.reference.id == dummy_sql_ref.id
    assert domain_enh.reference.visibility == dummy_sql_ref.visibility


@pytest.mark.asyncio
async def test_enhancement_request_from_and_to_domain():
    # Create dummy domain enhancement reqest
    dummy_enh_req = DummyDomainEnhancementRequest(
        id=uuid.uuid4(),
        reference_id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.FAILED,
        enhancement_parameters={"some": "parameter"},
        error="Didn't work",
    )

    # # Convert from domain to SQL model
    sql_enh_req = EnhancementRequest.from_domain(dummy_enh_req)
    assert sql_enh_req.id == dummy_enh_req.id
    assert sql_enh_req.reference_id == dummy_enh_req.reference_id
    assert sql_enh_req.robot_id == dummy_enh_req.robot_id
    assert sql_enh_req.request_status == dummy_enh_req.request_status
    assert sql_enh_req.enhancement_parameters == dummy_enh_req.enhancement_parameters

    assert sql_enh_req.error == dummy_enh_req.error

    # For preload test, assign a dummy SQL Reference to the relationship
    sql_enh_req.reference = Reference(
        id=dummy_enh_req.reference_id, visibility=Visibility.HIDDEN
    )

    # # Convert back to domain with preload reference
    domain_enh_req = sql_enh_req.to_domain(preload=["reference"])
    assert domain_enh_req.id == dummy_enh_req.id
    assert domain_enh_req.reference_id == dummy_enh_req.reference_id
    assert domain_enh_req.robot_id == dummy_enh_req.robot_id
    assert domain_enh_req.request_status == dummy_enh_req.request_status
    assert domain_enh_req.enhancement_parameters == dummy_enh_req.enhancement_parameters
    assert domain_enh_req.error == dummy_enh_req.error
    assert domain_enh_req.reference.id == dummy_enh_req.reference_id


@pytest.mark.asyncio
async def test_reference_with_relationships():
    # Create dummy domain external identifier and enhancement
    ref_id = uuid.uuid4()
    dummy_ext = DummyDomainExternalIdentifier(
        id=uuid.uuid4(),
        reference_id=ref_id,
        identifier_type=ExternalIdentifierType.PM_ID,
        identifier="123456",
    )
    dummy_content = DummyContent()
    dummy_enh = DummyDomainEnhancement(
        id=uuid.uuid4(),
        reference_id=ref_id,
        source="annotation_source",
        visibility=Visibility.RESTRICTED,
        robot_version="2.0.0",
        content=dummy_content,
    )

    # Create a canonical reference
    canonical_ref_id = uuid.uuid4()
    canonical_dummy_ref = DummyDomainReference(
        id=canonical_ref_id,
        visibility=Visibility.PUBLIC,
    )

    # Create a duplicate reference
    duplicate_ref_id = uuid.uuid4()
    duplicate_dummy_ref = DummyDomainReference(
        id=duplicate_ref_id,
        visibility=Visibility.HIDDEN,
    )

    # Create dummy domain reference with identifiers, enhancements, and refs
    dummy_ref = DummyDomainReference(
        id=ref_id,
        visibility=Visibility.PUBLIC,
        identifiers=[dummy_ext],
        enhancements=[dummy_enh],
        canonical_reference=canonical_dummy_ref,
    )

    # Convert the reference from domain
    sql_ref = Reference.from_domain(dummy_ref)
    # Manually assign SQL models for relationships
    sql_ext = ExternalIdentifier.from_domain(dummy_ext)
    sql_enh = Enhancement.from_domain(dummy_enh)
    sql_ref.identifiers = [sql_ext]
    sql_ref.enhancements = [sql_enh]

    # Create SQL model for canonical reference
    sql_canonical_ref = Reference.from_domain(canonical_dummy_ref)
    sql_ref.canonical_reference = sql_canonical_ref

    # Create SQL model for duplicate reference
    sql_duplicate_ref = Reference.from_domain(duplicate_dummy_ref)
    sql_ref.duplicate_references = [sql_duplicate_ref]

    # Convert back to domain with preload relationships
    domain_ref = sql_ref.to_domain(
        preload=[
            "identifiers",
            "enhancements",
            "canonical_reference",
            "duplicate_references",
        ]
    )
    assert domain_ref.id == dummy_ref.id
    assert domain_ref.visibility == dummy_ref.visibility

    # Check identifiers conversion
    assert isinstance(domain_ref.identifiers, list)
    assert len(domain_ref.identifiers) == 1
    assert domain_ref.identifiers[0].id == dummy_ext.id

    # Check enhancements conversion
    assert isinstance(domain_ref.enhancements, list)
    assert len(domain_ref.enhancements) == 1
    assert domain_ref.enhancements[0].id == dummy_enh.id

    # Check canonical reference conversion
    assert domain_ref.canonical_reference is not None
    assert domain_ref.canonical_reference.id == canonical_ref_id
    assert domain_ref.canonical_reference.visibility == Visibility.PUBLIC

    # Check duplicate references conversion
    assert domain_ref.duplicate_references is not None
    assert isinstance(domain_ref.duplicate_references, list)
    assert len(domain_ref.duplicate_references) == 1
    assert domain_ref.duplicate_references[0].id == duplicate_ref_id
    assert domain_ref.duplicate_references[0].visibility == Visibility.HIDDEN
