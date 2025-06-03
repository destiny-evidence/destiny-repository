"""Unit tests for the models in the references module."""

import uuid

import destiny_sdk

from app.domain.references.models.models import (
    EnhancementRequest,
    GenericExternalIdentifier,
    LinkedExternalIdentifier,
)
from app.domain.references.models.validators import ReferenceCreateResult


async def test_generic_external_identifier_from_specific_without_other():
    doi = destiny_sdk.identifiers.DOIIdentifier(
        identifier="10.1000/abc123", identifier_type="doi"
    )
    gen = await GenericExternalIdentifier.from_specific(doi)
    assert gen.identifier == "10.1000/abc123"
    assert gen.identifier_type == "doi"
    assert gen.other_identifier_name is None


async def test_generic_external_identifier_from_specific_with_other():
    other = destiny_sdk.identifiers.OtherIdentifier(
        identifier="123", identifier_type="other", other_identifier_name="isbn"
    )
    gen = await GenericExternalIdentifier.from_specific(other)
    assert gen.identifier == "123"
    assert gen.identifier_type == "other"
    assert gen.other_identifier_name == "isbn"


def test_reference_create_result_error_str_none():
    result = ReferenceCreateResult()
    assert result.error_str is None


def test_reference_create_result_error_str_multiple():
    result = ReferenceCreateResult(errors=["first error", " second error "])
    # strips and joins with blank line
    assert result.error_str == "first error\n\nsecond error"


async def test_linked_external_identifier_roundtrip():
    sdk_id = destiny_sdk.identifiers.PubMedIdentifier(
        identifier=1234, identifier_type="pm_id"
    )
    sdk_linked = destiny_sdk.identifiers.LinkedExternalIdentifier(
        identifier=sdk_id, reference_id=(u := uuid.uuid4())
    )
    domain = await LinkedExternalIdentifier.from_sdk(sdk_linked)
    assert domain.identifier == sdk_id
    assert domain.reference_id == u

    back = await domain.to_sdk()
    assert isinstance(back, destiny_sdk.identifiers.LinkedExternalIdentifier)
    assert back.reference_id == sdk_linked.reference_id
    assert back.identifier == sdk_id


async def test_enhancement_request_roundtrip():
    rid = uuid.uuid4()
    req_in = destiny_sdk.robots.EnhancementRequestIn(
        reference_id=rid, robot_id=rid, enhancement_parameters={"param": 42}
    )
    domain = await EnhancementRequest.from_sdk(req_in)
    assert domain.reference_id == rid
    assert domain.robot_id == rid
    assert domain.enhancement_parameters == {"param": 42}

    sdk_read = await domain.to_sdk()
    assert isinstance(sdk_read, destiny_sdk.robots.EnhancementRequestRead)
    assert sdk_read.reference_id == rid
    assert sdk_read.robot_id == rid
    assert sdk_read.enhancement_parameters == {"param": 42}
