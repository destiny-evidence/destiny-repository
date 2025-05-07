import json
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
    def __init__(self, id, visibility, identifiers=None, enhancements=None):
        self.id = id
        self.visibility = visibility
        self.identifiers = identifiers
        self.enhancements = enhancements


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

    def model_dump_json(self):
        return json.dumps(
            {
                "enhancement_type": "annotation",
                "annotations": [
                    {
                        "annotation_type": "test_annotation",
                        "label": "test_label",
                        "data": {"foo": "bar"},
                    }
                ],
            }
        )


class DummyDomainEnhancement:
    def __init__(
        self,
        id,
        reference_id,
        source,
        visibility,
        processor_version,
        content_version,
        content,
    ):
        self.id = id
        self.reference_id = reference_id
        self.source = source
        self.visibility = visibility
        self.processor_version = processor_version
        self.content_version = content_version
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
        error=None,
    ):
        self.id = id
        self.reference_id = reference_id
        self.robot_id = robot_id
        self.request_status = request_status
        self.enhancement_parameters = enhancement_parameters
        self.error = error


@pytest.mark.asyncio
async def test_reference_from_and_to_domain_without_preload():
    # Create dummy domain reference without identifiers and enhancements
    ref_id = uuid.uuid4()
    dummy_ref = DummyDomainReference(id=ref_id, visibility=Visibility.PUBLIC)

    # Convert from domain to SQL model
    sql_ref = await Reference.from_domain(dummy_ref)
    assert sql_ref.id == dummy_ref.id
    assert sql_ref.visibility == dummy_ref.visibility

    # When no preload is requested, to_domain should yield None for relationships
    domain_ref = await sql_ref.to_domain(preload=[])
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
    sql_ext = await ExternalIdentifier.from_domain(dummy_ext)
    assert sql_ext.id == dummy_ext.id
    assert sql_ext.reference_id == dummy_ext.reference_id
    assert sql_ext.identifier_type == dummy_ext.identifier.identifier_type
    assert sql_ext.identifier == dummy_ext.identifier.identifier

    # For preload test, assign a dummy SQL Reference to the relationship
    dummy_sql_ref = Reference(id=ref_id, visibility=Visibility.RESTRICTED)
    sql_ext.reference = dummy_sql_ref

    # Convert back to domain with preload reference
    domain_ext = await sql_ext.to_domain(preload=["reference"])
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
    content_version = uuid.uuid4()
    dummy_enh = DummyDomainEnhancement(
        id=enh_id,
        reference_id=ref_id,
        source="test_source",
        visibility=Visibility.PUBLIC,
        processor_version="1.0.0",
        content_version=content_version,
        content=dummy_content,
    )

    # Convert from domain to SQL model
    sql_enh = await Enhancement.from_domain(dummy_enh)
    assert sql_enh.id == dummy_enh.id
    assert sql_enh.reference_id == dummy_enh.reference_id
    assert sql_enh.enhancement_type == dummy_enh.content.enhancement_type
    assert sql_enh.source == dummy_enh.source
    assert sql_enh.visibility == dummy_enh.visibility
    assert sql_enh.processor_version == dummy_enh.processor_version
    assert sql_enh.content_version == dummy_enh.content_version
    # Verify that content was dumped to JSON string correctly
    dumped = dummy_content.model_dump_json()
    assert json.loads(sql_enh.content) == json.loads(dumped)

    # For preload test, assign a dummy SQL Reference to the relationship
    dummy_sql_ref = Reference(id=ref_id, visibility=Visibility.HIDDEN)
    sql_enh.reference = dummy_sql_ref

    # Convert back to domain with preload reference
    domain_enh = await sql_enh.to_domain(preload=["reference"])
    assert domain_enh.id == dummy_enh.id
    assert domain_enh.reference_id == dummy_enh.reference_id
    assert domain_enh.content.enhancement_type == dummy_enh.content.enhancement_type
    assert domain_enh.source == dummy_enh.source
    assert domain_enh.visibility == dummy_enh.visibility
    assert domain_enh.processor_version == dummy_enh.processor_version
    assert domain_enh.content_version == dummy_enh.content_version
    # Verify that content was loaded correctly
    assert domain_enh.content == destiny_sdk.enhancements.AnnotationEnhancement(
        **json.loads(sql_enh.content)
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
    sql_enh_req = await EnhancementRequest.from_domain(dummy_enh_req)
    assert sql_enh_req.id == dummy_enh_req.id
    assert sql_enh_req.reference_id == dummy_enh_req.reference_id
    assert sql_enh_req.robot_id == dummy_enh_req.robot_id
    assert sql_enh_req.request_status == dummy_enh_req.request_status
    assert sql_enh_req.enhancement_parameters == json.dumps(
        dummy_enh_req.enhancement_parameters
    )
    assert sql_enh_req.error == dummy_enh_req.error

    # For preload test, assign a dummy SQL Reference to the relationship
    sql_enh_req.reference = Reference(
        id=dummy_enh_req.reference_id, visibility=Visibility.HIDDEN
    )

    # # Convert back to domain with preload reference
    domain_enh_req = await sql_enh_req.to_domain(preload=["reference"])
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
        processor_version="2.0.0",
        content_version=uuid.uuid4(),
        content=dummy_content,
    )
    # Create dummy domain reference with identifiers and enhancements
    dummy_ref = DummyDomainReference(
        id=ref_id,
        visibility=Visibility.PUBLIC,
        identifiers=[dummy_ext],
        enhancements=[dummy_enh],
    )
    # Convert the reference from domain
    sql_ref = await Reference.from_domain(dummy_ref)
    # Manually assign SQL models for relationships
    sql_ext = await ExternalIdentifier.from_domain(dummy_ext)
    sql_enh = await Enhancement.from_domain(dummy_enh)
    sql_ref.identifiers = [sql_ext]
    sql_ref.enhancements = [sql_enh]

    # Convert back to domain with preload relationships
    domain_ref = await sql_ref.to_domain(preload=["identifiers", "enhancements"])
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
