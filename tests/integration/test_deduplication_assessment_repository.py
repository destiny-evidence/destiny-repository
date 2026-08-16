"""
Integration tests for deduplication assessment persistence.

Covers what the recorder's unit tests cannot: that the candidate set survives a
JSONB round-trip, that a policy generation's population is listable, and that the
repository is reachable only through an active unit of work.
"""

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import (
    AssessmentCandidateSummary,
    AssessmentPayloadState,
    DeduplicationAssessmentPurpose,
    DeduplicationAssessmentRecord,
    RetrievalPolicyName,
)
from app.domain.references.repository import (
    DeduplicationAssessmentSQLRepository,
    ReferenceSQLRepository,
)
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.factories import ReferenceFactory
from tests.unit.domain.references.deduplication.test_assessment_record import (
    build_assessment,
    scored_candidate,
)

pytestmark = pytest.mark.usefixtures("session")


@pytest.fixture
def repository(session: AsyncSession) -> DeduplicationAssessmentSQLRepository:
    """Create an assessment repository over the test session."""
    return DeduplicationAssessmentSQLRepository(session)


def build_record(
    policy_generation: str = "openalex-2026-08-a",
    *,
    probability: float = 0.95,
    proposed_duplicate_of_id: UUID | None = None,
) -> DeduplicationAssessmentRecord:
    """Build a record the way the recorder would, without persisting it."""
    assessment = build_assessment(
        [scored_candidate(probability), scored_candidate(0.12, rank=2)]
    )
    return DeduplicationAssessmentRecord(
        incoming_reference_id=assessment.incoming_reference_id,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=policy_generation,
        retrieval_policy=assessment.candidate_selection.retrieval_policy,
        k=assessment.candidate_selection.k_requested,
        candidate_count=assessment.candidate_selection.diagnostics.candidate_count,
        es_route_ran=True,
        es_index_name=assessment.candidate_selection.index_version,
        deduper_version=assessment.deduper.package_version,
        deduper_config_hash=assessment.deduper.configuration_hash,
        threshold=assessment.deduper.threshold,
        outcome=assessment.outcome,
        proposed_duplicate_of_id=proposed_duplicate_of_id,
        best_score=probability,
        best_non_winning_score=0.12,
        scored_candidates=[
            AssessmentCandidateSummary.from_scored_candidate(scored)
            for scored in assessment.scored_candidates
        ],
        payload_state=AssessmentPayloadState.NOT_RETAINED,
    )


async def test_candidate_set_survives_a_jsonb_round_trip(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """Candidate routes and scores survive storage as JSONB."""
    record = build_record()

    await repository.add(record)
    fetched = await repository.get_by_pk(record.id)

    assert fetched is not None
    assert len(fetched.scored_candidates) == len(record.scored_candidates)
    for stored, original in zip(
        fetched.scored_candidates, record.scored_candidates, strict=True
    ):
        assert stored.reference_id == original.reference_id
        assert stored.routes[0].type == original.routes[0].type
        assert stored.probability == pytest.approx(original.probability)
        assert stored.clears_threshold == original.clears_threshold


async def test_retrieval_policy_and_enums_round_trip_as_strings(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """Enums stored as varchar come back as their enum members."""
    record = build_record()

    await repository.add(record)
    fetched = await repository.get_by_pk(record.id)

    assert fetched.retrieval_policy == RetrievalPolicyName.CURRENT_FUZZY_V1
    assert fetched.purpose == DeduplicationAssessmentPurpose.DEDUPLICATION
    assert fetched.payload_state == AssessmentPayloadState.NOT_RETAINED
    assert fetched.outcome == record.outcome


async def test_records_are_listable_by_policy_generation(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """A policy generation's population is findable over its index."""
    for _ in range(3):
        await repository.add(build_record("openalex-2026-08-a"))
    await repository.add(build_record("openalex-2026-08-b"))

    found = await repository.find(policy_generation="openalex-2026-08-a")

    assert len(found) == 3
    assert {record.policy_generation for record in found} == {"openalex-2026-08-a"}


async def test_payload_location_can_be_attached_after_insert(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """The payload location can be written back after the summary row."""
    record = build_record()
    await repository.add(record)

    updated = await repository.update_by_pk(
        record.id,
        payload_state=AssessmentPayloadState.STORED,
        payload_blob_url="minio://operations/deduplication-assessments/x.json",
    )

    assert updated.payload_state == AssessmentPayloadState.STORED
    assert updated.payload_blob_url is not None
    assert updated.payload_blob_url.endswith("x.json")


async def test_proposed_canonical_references_a_held_reference(
    repository: DeduplicationAssessmentSQLRepository,
    session: AsyncSession,
) -> None:
    """The proposed canonical is constrained to a held reference."""
    canonical = await ReferenceSQLRepository(session).add(ReferenceFactory.build())

    record = build_record(proposed_duplicate_of_id=canonical.id)
    await repository.add(record)

    fetched = await repository.get_by_pk(record.id)
    assert fetched.proposed_duplicate_of_id == canonical.id


async def test_repository_is_unreachable_outside_an_active_unit_of_work(
    session: AsyncSession,
) -> None:
    """The repository is guarded by the unit-of-work active check."""
    unit_of_work = AsyncSqlUnitOfWork(session)

    with pytest.raises(RuntimeError, match="not active"):
        _ = unit_of_work.deduplication_assessments

    async with unit_of_work:
        assert unit_of_work.deduplication_assessments is not None
