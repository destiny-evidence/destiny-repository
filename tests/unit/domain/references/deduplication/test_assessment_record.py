from uuid import UUID, uuid7

import pytest

from app.core.exceptions import MinioBlobStorageError
from app.domain.references.models.models import (
    AssessmentPayloadState,
    Candidate,
    CandidateElasticsearchRoute,
    CandidateSelectionDiagnostics,
    CandidateSelectionResult,
    DeduperMetadata,
    DeduplicationAssessment,
    DeduplicationAssessmentOutcome,
    DeduplicationAssessmentPurpose,
    DeduplicationAssessmentRecord,
    DeduplicationPairResult,
    InputSearchability,
    RetrievalPolicyName,
    ScoredDeduplicationCandidate,
)
from app.domain.references.services.deduplication_assessment_recorder import (
    DeduplicationAssessmentRecorder,
)

POLICY_GENERATION = "openalex-2026-08-a"


class FakeRecordStore:
    """In-memory stand-in for the assessment record repository."""

    def __init__(self) -> None:
        self.records: dict[UUID, DeduplicationAssessmentRecord] = {}
        self.added: list[DeduplicationAssessmentRecord] = []

    async def add(
        self, record: DeduplicationAssessmentRecord
    ) -> DeduplicationAssessmentRecord:
        self.records[record.id] = record
        self.added.append(record)
        return record

    async def update_by_pk(
        self, pk: UUID, **kwargs: object
    ) -> DeduplicationAssessmentRecord:
        updated = self.records[pk].model_copy(update=kwargs)
        self.records[pk] = updated
        return updated


class FakePayloadWriter:
    """Payload writer that records its calls and can be made to fail."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[UUID] = []
        self._error = error

    async def write(self, record_id: UUID, assessment: DeduplicationAssessment) -> str:
        self.calls.append(record_id)
        if self._error:
            raise self._error
        return f"assessments/{record_id}.json"


def scored_candidate(
    probability: float | None = None,
    *,
    rank: int = 1,
    unscorable_reason: str | None = None,
) -> tuple[Candidate, DeduplicationPairResult]:
    candidate = Candidate(
        reference_id=uuid7(),
        rank=rank,
        routes=[
            CandidateElasticsearchRoute(
                policy=RetrievalPolicyName.CURRENT_FUZZY_V1, rank=rank, score=12.5
            )
        ],
    )
    pair_result = DeduplicationPairResult(
        probability=probability, unscorable_reason=unscorable_reason
    )
    return candidate, pair_result


def build_assessment(
    pairs: list[tuple[Candidate, DeduplicationPairResult]],
    *,
    threshold: float = 0.8,
    searchable: bool = True,
    index_version: str | None = "reference-000042",
) -> DeduplicationAssessment:
    """Assemble an assessment the way the assessment service would."""
    scored = [
        ScoredDeduplicationCandidate(
            candidate=candidate,
            pair_result=pair_result,
            clears_threshold=(
                pair_result.probability >= threshold
                if pair_result.probability is not None
                else None
            ),
        )
        for candidate, pair_result in pairs
    ]
    clearing = [s.candidate.reference_id for s in scored if s.clears_threshold is True]
    unscorable = [
        s.candidate.reference_id for s in scored if s.clears_threshold is None
    ]
    if unscorable or len(clearing) > 1:
        outcome = DeduplicationAssessmentOutcome.NO_PROPOSAL
        proposed = None
    elif clearing:
        outcome = DeduplicationAssessmentOutcome.PROPOSE_DUPLICATE
        proposed = clearing[0]
    elif not searchable:
        outcome = DeduplicationAssessmentOutcome.NO_PROPOSAL
        proposed = None
    else:
        outcome = DeduplicationAssessmentOutcome.PROPOSE_CANONICAL
        proposed = None

    return DeduplicationAssessment(
        incoming_reference_id=uuid7(),
        candidate_selection=CandidateSelectionResult(
            retrieval_policy=RetrievalPolicyName.CURRENT_FUZZY_V1,
            index_version=index_version,
            k_requested=10,
            input_searchability=InputSearchability(
                searchable=searchable, reason="test input"
            ),
            diagnostics=CandidateSelectionDiagnostics(
                es_returned=len(pairs), candidate_count=len(pairs)
            ),
            candidates=[candidate for candidate, _ in pairs],
        ),
        deduper=DeduperMetadata(
            package_version="0.4.1",
            configuration_hash="abc123",
            threshold=threshold,
        ),
        scored_candidates=scored,
        outcome=outcome,
        proposed_duplicate_of_id=proposed,
        threshold_clearing_candidate_ids=clearing,
        unscorable_candidate_ids=unscorable,
    )


@pytest.fixture
def record_store() -> FakeRecordStore:
    return FakeRecordStore()


@pytest.fixture
def payload_writer() -> FakePayloadWriter:
    return FakePayloadWriter()


@pytest.fixture
def recorder(
    record_store: FakeRecordStore, payload_writer: FakePayloadWriter
) -> DeduplicationAssessmentRecorder:
    return DeduplicationAssessmentRecorder(
        record_store=record_store, payload_writer=payload_writer
    )


async def test_below_threshold_assessment_is_recorded_without_a_payload(
    recorder: DeduplicationAssessmentRecorder,
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.2), scored_candidate(0.31, rank=2)]
    )

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.payload_state == AssessmentPayloadState.NOT_RETAINED
    assert record.payload_blob_url is None
    assert payload_writer.calls == []
    assert len(record_store.added) == 1


async def test_threshold_clearing_assessment_stores_a_payload(
    recorder: DeduplicationAssessmentRecorder,
    payload_writer: FakePayloadWriter,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.95), scored_candidate(0.1, rank=2)]
    )

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.payload_state == AssessmentPayloadState.STORED
    assert record.payload_blob_url == f"assessments/{record.id}.json"
    assert payload_writer.calls == [record.id]


async def test_unscorable_candidate_stores_a_payload_despite_no_proposal(
    recorder: DeduplicationAssessmentRecorder,
    payload_writer: FakePayloadWriter,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.2), scored_candidate(unscorable_reason="no title", rank=2)]
    )

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.outcome == DeduplicationAssessmentOutcome.NO_PROPOSAL
    assert record.payload_state == AssessmentPayloadState.STORED
    assert payload_writer.calls == [record.id]


async def test_best_non_winning_score_is_the_runner_up_behind_a_proposal(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.95), scored_candidate(0.44, rank=2)]
    )

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.best_score == pytest.approx(0.95)
    assert record.best_non_winning_score == pytest.approx(0.44)


async def test_best_non_winning_score_is_the_top_score_when_nothing_cleared(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.44), scored_candidate(0.2, rank=2)]
    )

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.best_score == pytest.approx(0.44)
    assert record.best_non_winning_score == pytest.approx(0.44)


async def test_assessment_without_candidates_has_no_scores(
    recorder: DeduplicationAssessmentRecorder,
    payload_writer: FakePayloadWriter,
) -> None:
    record = await recorder.record(
        build_assessment([]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.best_score is None
    assert record.best_non_winning_score is None
    assert record.candidate_count == 0
    assert payload_writer.calls == []


async def test_record_carries_its_purpose(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    record = await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.PERFORMANCE_SHADOW,
        policy_generation=POLICY_GENERATION,
    )

    assert record.purpose == DeduplicationAssessmentPurpose.PERFORMANCE_SHADOW


async def test_retrieval_and_deduper_provenance_is_recorded(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    assessment = build_assessment([scored_candidate(0.2)])

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.policy_generation == POLICY_GENERATION
    assert record.retrieval_policy == RetrievalPolicyName.CURRENT_FUZZY_V1
    assert record.k == 10
    assert record.candidate_count == 1
    assert record.es_route_ran is True
    assert record.es_index_name == "reference-000042"
    assert record.deduper_version == "0.4.1"
    assert record.deduper_config_hash == "abc123"
    assert record.threshold == pytest.approx(0.8)
    assert record.incoming_reference_id == assessment.incoming_reference_id


async def test_unsearchable_input_records_that_the_es_route_did_not_run(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    assessment = build_assessment([], searchable=False, index_version=None)

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.es_route_ran is False
    assert record.es_index_name is None


async def test_failed_payload_write_keeps_the_summary_record(
    record_store: FakeRecordStore,
) -> None:
    recorder = DeduplicationAssessmentRecorder(
        record_store=record_store,
        payload_writer=FakePayloadWriter(error=MinioBlobStorageError("bucket gone")),
    )

    record = await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert record.payload_state == AssessmentPayloadState.FAILED
    assert record.payload_blob_url is None
    assert record.payload_reason is not None
    assert "bucket gone" in record.payload_reason
    assert record_store.records[record.id].payload_state == (
        AssessmentPayloadState.FAILED
    )


async def test_scored_candidates_are_retained_on_the_record(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.95), scored_candidate(0.2, rank=2)]
    )

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
    )

    assert [c.candidate.reference_id for c in record.scored_candidates] == [
        s.candidate.reference_id for s in assessment.scored_candidates
    ]
    assert record.proposed_duplicate_of_id == assessment.proposed_duplicate_of_id
