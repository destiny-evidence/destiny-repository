"""
Integration tests for deduplication assessment persistence.

Covers what the recorder's unit tests cannot: that the candidate set survives a
JSONB round-trip, that a policy generation's population is listable, that the
idempotent writer resolves collisions, and that the repository is reachable only
through an active unit of work.
"""

from uuid import UUID, uuid7

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SQLIntegrityError
from app.domain.references.models.models import (
    AssessmentCandidateSummary,
    AssessmentPayloadState,
    CandidateIdentifier,
    CandidateIdentifierRoute,
    DeduplicationAssessmentPurpose,
    DeduplicationAssessmentRecord,
    ExternalIdentifierType,
    RetrievalPolicyName,
)
from app.domain.references.repository import (
    DeduplicationAssessmentSQLRepository,
    ReferenceSQLRepository,
)
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.factories import ReferenceFactory
from tests.unit.domain.references.deduplication.test_assessment_record import (
    POLICY_GENERATION,
    build_assessment,
    scored_candidate,
)

pytestmark = pytest.mark.usefixtures("session")

# Shares no component with POLICY_GENERATION, so a listing that ignored the filter
# cannot be mistaken for one that applied it.
UNRELATED_GENERATION = "crossref-backfill-2027-01"


@pytest.fixture
def repository(session: AsyncSession) -> DeduplicationAssessmentSQLRepository:
    """Create an assessment repository over the test session."""
    return DeduplicationAssessmentSQLRepository(session)


def build_record(
    policy_generation: str = POLICY_GENERATION,
    *,
    probability: float = 0.95,
    proposed_duplicate_of_id: UUID | None = None,
    payload_sampled: bool = False,
) -> DeduplicationAssessmentRecord:
    """Build a record the way the recorder would, without persisting it."""
    assessment = build_assessment(
        [scored_candidate(probability), scored_candidate(0.12, rank=2)]
    )
    return DeduplicationAssessmentRecord(
        idempotency_key=uuid7(),
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
        payload_sampled=payload_sampled,
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


async def test_identifier_route_survives_a_jsonb_round_trip(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """A matched-identifier route rebuilds with its identifiers intact."""
    # Routes are a discriminated union rebuilt by model_validate, and this is the only
    # arm carrying nested objects. The Elasticsearch arm cannot exercise that shape.
    record = build_record()
    record.scored_candidates[0].routes = [
        CandidateIdentifierRoute(
            matched_identifiers=[
                CandidateIdentifier(
                    identifier="10.1234/abc", identifier_type=ExternalIdentifierType.DOI
                )
            ]
        )
    ]

    await repository.add(record)
    fetched = await repository.get_by_pk(record.id)

    route = fetched.scored_candidates[0].routes[0]
    assert isinstance(route, CandidateIdentifierRoute)
    assert [i.identifier for i in route.matched_identifiers] == ["10.1234/abc"]
    assert route.matched_identifiers[0].identifier_type == ExternalIdentifierType.DOI


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
    """A policy generation's population is findable."""
    for _ in range(3):
        await repository.add(build_record(POLICY_GENERATION))
    await repository.add(build_record(UNRELATED_GENERATION))

    found = await repository.find(policy_generation=POLICY_GENERATION)

    assert len(found) == 3
    assert {record.policy_generation for record in found} == {POLICY_GENERATION}


async def test_sample_membership_survives_the_round_trip(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """Sample membership is readable back, so the sampled population is listable."""
    record = build_record(payload_sampled=True)

    await repository.add(record)
    fetched = await repository.get_by_pk(record.id)

    assert fetched.payload_sampled is True


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


async def test_proposed_canonical_that_is_not_held_is_rejected(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """An unheld proposed canonical is refused by the foreign key."""
    # The asymmetry this defends is deliberate: incoming_reference_id is intentionally
    # unconstrained, so only this side proves the constraint is actually present.
    record = build_record(proposed_duplicate_of_id=uuid7())

    with pytest.raises(SQLIntegrityError):
        await repository.add(record)


@pytest.mark.parametrize(
    ("state", "blob_url", "payload_bytes"),
    [
        pytest.param(AssessmentPayloadState.STORED, None, 10, id="stored-without-url"),
        pytest.param(
            AssessmentPayloadState.NOT_RETAINED,
            "minio://operations/x.json",
            None,
            id="unretained-with-url",
        ),
        pytest.param(
            AssessmentPayloadState.NOT_RETAINED, None, 10, id="unretained-with-bytes"
        ),
    ],
)
async def test_incoherent_payload_state_is_rejected(
    repository: DeduplicationAssessmentSQLRepository,
    state: AssessmentPayloadState,
    blob_url: str | None,
    payload_bytes: int | None,
) -> None:
    """The database refuses payload columns that contradict the payload state."""
    # update_by_pk writes attributes straight onto the persistence object with no model
    # validation, so a check constraint is the only guard on the real write path.
    record = build_record()
    record.payload_state = state
    record.payload_blob_url = blob_url
    record.payload_bytes = payload_bytes

    with pytest.raises(SQLIntegrityError):
        await repository.add(record)


async def test_one_attempt_cannot_write_two_records(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """The database refuses a second record for the same delivery."""
    # The recorder looks the key up before writing, but two concurrent redeliveries
    # can both miss that read; the constraint is what makes the second one fail.
    attempt = uuid7()
    first = build_record()
    first.idempotency_key = attempt
    await repository.add(first)

    second = build_record()
    second.idempotency_key = attempt

    with pytest.raises(SQLIntegrityError):
        await repository.add(second)


async def test_idempotent_add_returns_the_existing_record(
    repository: DeduplicationAssessmentSQLRepository,
) -> None:
    """The idempotent writer resolves a unique-key collision to the stored row."""
    attempt = uuid7()
    first = build_record()
    first.idempotency_key = attempt
    await repository.add(first)

    second = build_record()
    second.idempotency_key = attempt

    returned = await repository.add_or_find_by_idempotency_key(second)

    assert returned.id == first.id
    assert returned.incoming_reference_id == first.incoming_reference_id


async def test_repository_is_unreachable_outside_an_active_unit_of_work(
    session: AsyncSession,
) -> None:
    """The repository is guarded by the unit-of-work active check."""
    unit_of_work = AsyncSqlUnitOfWork(session)

    with pytest.raises(RuntimeError, match="not active"):
        _ = unit_of_work.deduplication_assessments

    async with unit_of_work:
        assert unit_of_work.deduplication_assessments is not None
