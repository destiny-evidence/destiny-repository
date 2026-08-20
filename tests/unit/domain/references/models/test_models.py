"""Unit tests for the models in the references module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid7

import destiny_sdk
import pytest
from pydantic import ValidationError

from app.core.exceptions import SDKToDomainError
from app.domain.references.models.models import (
    AssessmentCandidateSummary,
    Candidate,
    CandidateCanonicalSearchFields,
    CandidateElasticsearchRoute,
    CandidateReference,
    DeduperMetadata,
    DeduplicationFieldComparison,
    DeduplicationFieldStatus,
    DeduplicationPairResult,
    DuplicateDetermination,
    Enhancement,
    FullTextEnhancement,
    GenericExternalIdentifier,
    ReferenceDuplicateDecision,
    ScoredDeduplicationCandidate,
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


def test_deduplication_pair_result_accepts_unscorable_reason_without_probability():
    result = DeduplicationPairResult(unscorable_reason="insufficient comparable fields")

    assert result.probability is None


@pytest.mark.parametrize(
    "data",
    [
        pytest.param({}, id="neither"),
        pytest.param(
            {
                "probability": 0.4,
                "unscorable_reason": "insufficient comparable fields",
            },
            id="both",
        ),
    ],
)
def test_deduplication_pair_result_rejects_ambiguous_scoring_state(data):
    with pytest.raises(ValueError, match="probability or unscorable_reason"):
        DeduplicationPairResult(**data)


@pytest.mark.parametrize("field_name", ["incoming_value", "candidate_value"])
def test_deduplication_field_comparison_rejects_non_json_values(field_name):
    with pytest.raises(ValidationError):
        DeduplicationFieldComparison(
            status=DeduplicationFieldStatus.COMPARED,
            **{field_name: object()},
        )


def _scored_candidate(
    field_comparisons=None,
    *,
    reference=None,
):
    return ScoredDeduplicationCandidate(
        candidate=Candidate(
            reference_id=uuid7(),
            rank=3,
            routes=[
                CandidateElasticsearchRoute(
                    policy="candidate_selection_v1", rank=3, score=9.5
                )
            ],
            reference=reference,
        ),
        pair_result=DeduplicationPairResult(
            probability=0.42,
            field_comparisons=field_comparisons or {},
        ),
        clears_threshold=False,
    )


def test_candidate_summary_carries_identity_and_retrieval_provenance():
    scored = _scored_candidate()

    summary = AssessmentCandidateSummary.from_scored_candidate(scored)

    assert summary.reference_id == scored.candidate.reference_id
    assert summary.rank == 3
    assert summary.routes == scored.candidate.routes
    assert summary.probability == pytest.approx(0.42)
    assert summary.clears_threshold is False


def test_candidate_summary_omits_compared_fields_from_availability():
    # Only absence belongs in the map. MISMATCH is the tempting one to keep, but it
    # would make a distrusted verdict durable and cost an entry on every field.
    scored = _scored_candidate(
        {
            "title": DeduplicationFieldComparison(
                status=DeduplicationFieldStatus.COMPARED, score=0.99
            ),
            "journal": DeduplicationFieldComparison(
                status=DeduplicationFieldStatus.COMPARED, score=0.2
            ),
        }
    )

    summary = AssessmentCandidateSummary.from_scored_candidate(scored)

    assert summary.field_availability == {}


def test_candidate_summary_records_which_side_a_field_was_missing_from():
    scored = _scored_candidate(
        {
            "journal": DeduplicationFieldComparison(
                status=DeduplicationFieldStatus.MISSING_CANDIDATE
            ),
            "pages": DeduplicationFieldComparison(
                status=DeduplicationFieldStatus.MISSING_BOTH
            ),
            "title": DeduplicationFieldComparison(
                status=DeduplicationFieldStatus.COMPARED, score=1.0
            ),
        }
    )

    summary = AssessmentCandidateSummary.from_scored_candidate(scored)

    assert summary.field_availability == {
        "journal": DeduplicationFieldStatus.MISSING_CANDIDATE,
        "pages": DeduplicationFieldStatus.MISSING_BOTH,
    }


def test_candidate_summary_rejects_compared_field_availability():
    with pytest.raises(ValidationError, match="COMPARED"):
        AssessmentCandidateSummary(
            reference_id=uuid7(),
            rank=1,
            routes=[],
            field_availability={"title": DeduplicationFieldStatus.COMPARED},
        )


def test_candidate_summary_never_carries_compared_values_or_scores():
    # Compared values are the bulk, titles most of all: present on nearly every
    # record and stored for both sides of every candidate pair.
    scored = _scored_candidate(
        {
            "title": DeduplicationFieldComparison(
                status=DeduplicationFieldStatus.COMPARED,
                score=0.97,
                incoming_value="A hydrated title",
                candidate_value="A hydrated title",
            ),
            "authors": DeduplicationFieldComparison(
                status=DeduplicationFieldStatus.COMPARED,
                score=0.88,
                incoming_value=["Ada Lovelace"],
                candidate_value=["Ada Lovelace"],
            ),
        },
        reference=CandidateReference(
            title="A hydrated title", authors=["Ada Lovelace"]
        ),
    )

    serialised = AssessmentCandidateSummary.from_scored_candidate(
        scored
    ).model_dump_json()

    assert "Ada Lovelace" not in serialised
    assert "A hydrated title" not in serialised
    assert "0.97" not in serialised


def test_deduper_metadata_rejects_non_json_configuration():
    with pytest.raises(ValidationError):
        DeduperMetadata(
            package_version="fake-1",
            configuration_hash="test-config",
            threshold=0.85,
            effective_configuration={"opaque": object()},
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


def test_full_text_enhancement_fingerprint_is_content_identity():
    """Fingerprint excludes transient storage details and tracks content fields.

    blob (where we stored it) and retrieved_at (when we fetched it) are
    incidental; sha256_checksum is the canonical content-identity field.
    """
    a = FullTextEnhancementFactory.build()

    # Same content, different storage/timing: fingerprint matches.
    same_content = a.model_copy(
        update={
            "retrieved_at": datetime(2020, 1, 1, tzinfo=UTC),
            "blob": BlobStorageFileFactory.build(),
        }
    )
    assert a.fingerprint == same_content.fingerprint

    # Different sha256: fingerprint diverges.
    different_content = a.model_copy(update={"sha256_checksum": "different"})
    assert a.fingerprint != different_content.fingerprint


@pytest.fixture
def anti_corruption_service() -> ReferenceAntiCorruptionService:
    return ReferenceAntiCorruptionService(sign_url=AsyncMock())


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


@pytest.mark.parametrize(
    ("duplicate_determination", "canonical_reference_id"),
    [
        (DuplicateDetermination.EXACT_DUPLICATE, None),
        (DuplicateDetermination.DUPLICATE, None),
        (DuplicateDetermination.PENDING, uuid7()),
        (DuplicateDetermination.CANONICAL, uuid7()),
    ],
)
def test_duplicate_decision_rejects_mismatched_canonical_reference(
    duplicate_determination, canonical_reference_id
):
    """The model is the only guard left on this pairing after the registrars split."""
    with pytest.raises(ValidationError, match="canonical_reference_id must be"):
        ReferenceDuplicateDecision(
            reference_id=uuid7(),
            duplicate_determination=duplicate_determination,
            canonical_reference_id=canonical_reference_id,
        )


def test_duplicate_decision_allows_decoupled_with_or_without_canonical():
    """DECOUPLED may retain a proposed canonical for later review."""
    canonical_id = uuid7()

    with_canonical = ReferenceDuplicateDecision(
        reference_id=uuid7(),
        duplicate_determination=DuplicateDetermination.DECOUPLED,
        canonical_reference_id=canonical_id,
    )
    without_canonical = ReferenceDuplicateDecision(
        reference_id=uuid7(),
        duplicate_determination=DuplicateDetermination.DECOUPLED,
    )

    assert with_canonical.canonical_reference_id == canonical_id
    assert without_canonical.canonical_reference_id is None
