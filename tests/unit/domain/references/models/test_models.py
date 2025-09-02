"""Unit tests for the models in the references module."""

import uuid

import destiny_sdk
import pytest

from app.core.exceptions import (
    SDKToDomainError,
)
from app.domain.references.models.models import (
    GenericExternalIdentifier,
)
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)


async def test_generic_external_identifier_from_specific_without_other():
    doi = destiny_sdk.identifiers.DOIIdentifier(
        identifier="10.1000/abc123", identifier_type="doi"
    )
    gen = GenericExternalIdentifier.from_specific(doi)
    assert gen.identifier == "10.1000/abc123"
    assert gen.identifier_type == "doi"
    assert gen.other_identifier_name is None


async def test_generic_external_identifier_from_specific_with_other():
    other = destiny_sdk.identifiers.OtherIdentifier(
        identifier="123", identifier_type="other", other_identifier_name="isbn"
    )
    gen = GenericExternalIdentifier.from_specific(other)
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


@pytest.fixture
def anti_corruption_service(fake_repository) -> ReferenceAntiCorruptionService:
    return ReferenceAntiCorruptionService(fake_repository)


async def test_linked_external_identifier_roundtrip(
    anti_corruption_service,
):
    sdk_id = destiny_sdk.identifiers.PubMedIdentifier(
        identifier=1234, identifier_type="pm_id"
    )
    sdk_linked = destiny_sdk.identifiers.LinkedExternalIdentifier(
        identifier=sdk_id, reference_id=(u := uuid.uuid4())
    )
    domain = anti_corruption_service.external_identifier_from_sdk(sdk_linked)
    assert domain.identifier == sdk_id
    assert domain.reference_id == u

    back = anti_corruption_service.external_identifier_to_sdk(domain)
    assert isinstance(back, destiny_sdk.identifiers.LinkedExternalIdentifier)
    assert back.reference_id == sdk_linked.reference_id
    assert back.identifier == sdk_id


async def test_enhancement_request_roundtrip(
    anti_corruption_service: ReferenceAntiCorruptionService,
):
    rid = uuid.uuid4()
    req_in = destiny_sdk.robots.EnhancementRequestIn(
        reference_id=rid, robot_id=rid, enhancement_parameters={"param": 42}
    )
    domain = anti_corruption_service.enhancement_request_from_sdk(req_in)
    assert domain.reference_id == rid
    assert domain.robot_id == rid
    assert domain.enhancement_parameters == {"param": 42}

    sdk_read = anti_corruption_service.enhancement_request_to_sdk(domain)
    assert isinstance(sdk_read, destiny_sdk.robots.EnhancementRequestRead)
    assert sdk_read.reference_id == rid
    assert sdk_read.robot_id == rid
    assert sdk_read.enhancement_parameters == {"param": 42}


async def test_enhancement_unserializable_failure(
    anti_corruption_service: ReferenceAntiCorruptionService,
):
    """Test that an enhancement with unserializable parameters raises an error."""
    dodgy_enhancement = destiny_sdk.enhancements.LocationEnhancement(
        locations=[
            destiny_sdk.enhancements.Location(
                # Example where input is not JSON serializable.
                # Serializing makes the URL longer than max length,
                # deserializing then fails.
                landing_page_url=r"http://obfuscated.org/doing-cool-researÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€š\Â¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§h-on-french-letters/1234"  # noqa: E501, RUF001
            )
        ],
    )
    with pytest.raises(SDKToDomainError):
        anti_corruption_service.enhancement_from_sdk(
            destiny_sdk.enhancements.Enhancement(
                reference_id=uuid.uuid4(),
                source="dummy",
                visibility="public",
                content=dodgy_enhancement,
            )
        )

    with pytest.raises(SDKToDomainError):
        anti_corruption_service.reference_from_sdk_file_input(
            destiny_sdk.references.ReferenceFileInput(
                identifiers=[
                    destiny_sdk.identifiers.DOIIdentifier(
                        identifier="10.1000/abc123", identifier_type="doi"
                    )
                ],
                enhancements=[
                    destiny_sdk.enhancements.EnhancementFileInput(
                        source="dummy",
                        visibility="public",
                        enhancement_type="location",
                        content=dodgy_enhancement,
                    )
                ],
            )
        )
