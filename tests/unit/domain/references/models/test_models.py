"""Unit tests for the models in the references module."""

from datetime import UTC, datetime
from uuid import uuid7

import destiny_sdk
import pytest

from app.core.exceptions import SDKToDomainError
from app.domain.references.models.models import (
    CandidateCanonicalSearchFields,
    Enhancement,
    FullTextEnhancement,
    GenericExternalIdentifier,
)
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.persistence.blob.models import BlobStorageFile
from tests.factories import (
    BlobStorageFileFactory,
    EnhancementFactory,
    FullTextEnhancementFactory,
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


def test_full_text_enhancement_discriminator_resolves_to_domain():
    """
    A FULL_TEXT payload resolves to the domain FullTextEnhancement.

    The SDK ships its own FullTextEnhancement with file_url: HttpUrl. The
    domain variant uses BlobStorageFile. If someone reorders the union or
    accidentally lists the SDK type in EnhancementContent, this round trip
    would fail.
    """
    full_text = FullTextEnhancementFactory.build()
    enhancement = EnhancementFactory.build(content=full_text)

    restored = Enhancement.model_validate(enhancement.model_dump())
    assert isinstance(restored.content, FullTextEnhancement)
    assert isinstance(restored.content.blob, BlobStorageFile)
    assert restored.content.blob == full_text.blob


def test_full_text_enhancement_json_mode_round_trip():
    """blob serializes to a URI string in JSON mode and re-parses on validate."""
    full_text = FullTextEnhancementFactory.build()
    enhancement = EnhancementFactory.build(content=full_text)

    dumped = enhancement.model_dump(mode="json")
    assert isinstance(dumped["content"]["blob"], str)

    restored = Enhancement.model_validate(dumped)
    assert isinstance(restored.content, FullTextEnhancement)
    assert restored.content.blob == full_text.blob


def test_full_text_enhancement_fingerprint_stable_across_identical_content():
    """Two full-texts with identical content fields share a fingerprint."""
    a = FullTextEnhancementFactory.build()
    b = a.model_copy(deep=True)
    assert a.fingerprint == b.fingerprint


def test_full_text_enhancement_fingerprint_ignores_retrieved_at_and_blob():
    """blob describes where we stored it, not what it is."""
    a = FullTextEnhancementFactory.build()
    b = a.model_copy(
        update={
            "retrieved_at": datetime(2020, 1, 1, tzinfo=UTC),
            "blob": BlobStorageFileFactory.build(),
        }
    )
    assert a.fingerprint == b.fingerprint


def test_full_text_enhancement_fingerprint_changes_with_content():
    """Changing the sha256 (the canonical content-identity field) shifts it."""
    a = FullTextEnhancementFactory.build()
    b = a.model_copy(update={"sha256_checksum": "different"})
    assert a.fingerprint != b.fingerprint


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
        identifier=sdk_id, reference_id=(u := uuid7())
    )
    domain = anti_corruption_service.external_identifier_from_sdk(sdk_linked)
    assert domain.identifier == sdk_id
    assert domain.reference_id == u

    back = anti_corruption_service.external_identifier_to_sdk(domain)
    assert isinstance(back, destiny_sdk.identifiers.LinkedExternalIdentifier)
    assert back.reference_id == sdk_linked.reference_id
    assert back.identifier == sdk_id


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
                reference_id=uuid7(),
                source="dummy",
                visibility="public",
                content=dodgy_enhancement,
                created_at=datetime.now(tz=UTC),
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


async def test_canonical_search_fields_searchable():
    """Test that a canonical search fields model is searchable with everything set"""
    search_fields = CandidateCanonicalSearchFields(
        title="Kiss from a Rose",
        authors=["Seal Henry Olusegun Olumide Adeola Samuel"],
        publication_year=2024,
    )

    assert search_fields.is_searchable

    # set publication year to None
    search_fields.publication_year = None

    assert not search_fields.is_searchable
