from uuid import UUID, uuid7

import pytest

from app.core.config import EVIDENCE_SAMPLE_DIGEST_BITS
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
    DeduplicationFieldComparison,
    DeduplicationPairResult,
    InputSearchability,
    RetrievalPolicyName,
    ScoredDeduplicationCandidate,
)
from app.domain.references.services.deduplication_assessment_recorder import (
    DeduplicationAssessmentRecorder,
    StoredPayload,
    evidence_sampled,
)

# Names a configuration generation, never an execution: it is the cohort every
# assessment row is grouped by, so a run id would make each run its own cohort.
POLICY_GENERATION = "openalex-probe-2026-08-a"


class FakeRecordStore:
    """In-memory stand-in for the assessment record repository."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.records: dict[UUID, DeduplicationAssessmentRecord] = {}
        self.added: list[DeduplicationAssessmentRecord] = []
        self.updates: list[UUID] = []
        self.events = events if events is not None else []

    async def add(
        self, record: DeduplicationAssessmentRecord
    ) -> DeduplicationAssessmentRecord:
        self.records[record.id] = record
        self.added.append(record)
        self.events.append("add")
        return record

    async def find(self, **filters: object) -> list[DeduplicationAssessmentRecord]:
        return [
            record
            for record in self.records.values()
            if all(getattr(record, k) == v for k, v in filters.items())
        ]

    async def update_by_pk(
        self, pk: UUID, **kwargs: object
    ) -> DeduplicationAssessmentRecord:
        updated = self.records[pk].model_copy(update=kwargs)
        self.records[pk] = updated
        self.updates.append(pk)
        self.events.append("update")
        return updated


class FailingOnceRecordStore(FakeRecordStore):
    """Record store whose first insert fails, as a rolled-back transaction would."""

    def __init__(self, events: list[str] | None = None) -> None:
        super().__init__(events=events)
        self._failed = False

    async def add(
        self, record: DeduplicationAssessmentRecord
    ) -> DeduplicationAssessmentRecord:
        if not self._failed:
            self._failed = True
            msg = "insert rolled back"
            raise RuntimeError(msg)
        return await super().add(record)


class FakePayloadWriter:
    """Payload writer that records its calls and can be made to fail."""

    def __init__(
        self,
        *,
        error: Exception | None = None,
        size_bytes: int = 1234,
        events: list[str] | None = None,
    ) -> None:
        self.calls: list[UUID] = []
        self.size_bytes = size_bytes
        self.events = events if events is not None else []
        self._error = error

    async def write(
        self, payload_id: UUID, assessment: DeduplicationAssessment
    ) -> StoredPayload:
        self.calls.append(payload_id)
        self.events.append("payload")
        if self._error:
            raise self._error
        return StoredPayload(
            location=f"assessments/{payload_id}.json", size_bytes=self.size_bytes
        )


def scored_candidate(
    probability: float | None = None,
    *,
    rank: int = 1,
    unscorable_reason: str | None = None,
    field_comparisons: dict[str, DeduplicationFieldComparison] | None = None,
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
        probability=probability,
        unscorable_reason=unscorable_reason,
        field_comparisons=field_comparisons or {},
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
def events() -> list[str]:
    """Shared ordering log so tests can assert payload-before-row."""
    return []


@pytest.fixture
def record_store(events: list[str]) -> FakeRecordStore:
    return FakeRecordStore(events=events)


@pytest.fixture
def payload_writer(events: list[str]) -> FakePayloadWriter:
    return FakePayloadWriter(events=events)


@pytest.fixture
def recorder(
    record_store: FakeRecordStore, payload_writer: FakePayloadWriter
) -> DeduplicationAssessmentRecorder:
    return DeduplicationAssessmentRecorder(
        record_store=record_store,
        payload_writer=payload_writer,
        evidence_sample_rate_bits=None,
    )


def _recorder_at(
    sample_rate_bits: int | None,
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> DeduplicationAssessmentRecorder:
    return DeduplicationAssessmentRecorder(
        record_store=record_store,
        payload_writer=payload_writer,
        evidence_sample_rate_bits=sample_rate_bits,
    )


@pytest.mark.parametrize(
    ("sample_rate_bits", "expected"),
    [pytest.param(None, False, id="never"), pytest.param(0, True, id="always")],
)
def test_evidence_sampling_honours_the_extremes(sample_rate_bits, expected):
    assert evidence_sampled(uuid7(), sample_rate_bits) is expected


@pytest.mark.parametrize("sample_rate_bits", [1, 2, 5])
def test_evidence_sampling_selects_the_configured_power_of_two_rate(
    sample_rate_bits: int,
):
    # More than one rate, so a hardcoded one cannot pass. At least one above 1,
    # because an off-by-one mask still selects about half at 1 and only shows above it.
    sample_size = 10_000
    expected = sample_size / (2**sample_rate_bits)

    selected = sum(
        evidence_sampled(uuid7(), sample_rate_bits) for _ in range(sample_size)
    )

    assert abs(selected - expected) < expected * 0.25


@pytest.mark.parametrize(
    "sample_rate_bits",
    [
        pytest.param(EVIDENCE_SAMPLE_DIGEST_BITS + 1, id="wider-than-digest"),
        pytest.param(-1, id="negative"),
    ],
)
def test_evidence_sampling_rejects_a_rate_the_digest_cannot_express(sample_rate_bits):
    # Masking past the digest matches nothing, so an unbounded rate would read as a
    # working configuration that silently keeps no evidence at all.
    with pytest.raises(ValueError, match="digest"):
        evidence_sampled(uuid7(), sample_rate_bits)


async def test_uninteresting_assessment_keeps_a_payload_when_sampled(
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    recorder = _recorder_at(0, record_store, payload_writer)
    attempt = uuid7()

    record = await recorder.record(
        build_assessment([scored_candidate(0.2)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=attempt,
    )

    assert record.payload_state == AssessmentPayloadState.STORED
    assert record.payload_sampled is True
    assert payload_writer.calls == [attempt]


async def test_interesting_assessment_is_kept_without_being_sampled(
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    # The flag marks sample membership, not the reason a payload exists. Folding the
    # two together would hide sampled-and-interesting records and bias the sample.
    recorder = _recorder_at(None, record_store, payload_writer)

    record = await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.payload_state == AssessmentPayloadState.STORED
    assert record.payload_sampled is False


async def test_stored_payload_records_its_size(
    record_store: FakeRecordStore,
) -> None:
    # The size is what makes narrowing the sample rate an evidence-based decision
    # rather than a guess.
    recorder = DeduplicationAssessmentRecorder(
        record_store=record_store,
        payload_writer=FakePayloadWriter(size_bytes=48_000),
        evidence_sample_rate_bits=0,
    )

    record = await recorder.record(
        build_assessment([scored_candidate(0.2)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.payload_bytes == 48_000


async def test_unretained_payload_has_no_size(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    record = await recorder.record(
        build_assessment([scored_candidate(0.2)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.payload_state == AssessmentPayloadState.NOT_RETAINED
    assert record.payload_bytes is None


async def test_redelivered_attempt_writes_one_record_and_one_payload(
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    # A redelivered task must not double the population or the storage bill. The
    # attempt identifies the delivery, so the replay resolves to the first record.
    recorder = _recorder_at(0, record_store, payload_writer)
    assessment = build_assessment([scored_candidate(0.95)])
    attempt = uuid7()

    first = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=attempt,
    )
    second = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=attempt,
    )

    assert second.id == first.id
    assert len(record_store.added) == 1
    assert payload_writer.calls == [attempt]


async def test_a_retried_delivery_reuses_the_payload_location(
    payload_writer: FakePayloadWriter,
) -> None:
    # The find-first guard only sees committed rows, so a delivery whose insert
    # rolled back retries with nothing to find. Naming the payload for the delivery
    # rather than the record is what stops that retry stranding a second blob.
    recorder = _recorder_at(0, FailingOnceRecordStore(), payload_writer)
    assessment = build_assessment([scored_candidate(0.95)])
    attempt = uuid7()

    with pytest.raises(RuntimeError, match="insert rolled back"):
        await recorder.record(
            assessment,
            purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
            policy_generation=POLICY_GENERATION,
            idempotency_key=attempt,
        )
    retried = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=attempt,
    )

    assert payload_writer.calls == [attempt, attempt]
    assert retried.payload_blob_url == f"assessments/{attempt}.json"


async def test_a_fresh_attempt_assesses_the_same_reference_again(
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    # Re-assessment under the same generation is legitimate: the corpus moves under a
    # stable configuration, so only the delivery is deduplicated, never the reference.
    recorder = _recorder_at(0, record_store, payload_writer)
    assessment = build_assessment([scored_candidate(0.95)])

    first = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )
    second = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert second.id != first.id
    assert len(record_store.added) == 2


async def test_reassessing_the_same_reference_reuses_sample_membership(
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    # Twenty, not two: keying off the row id would draw independently per assessment
    # row, so two records could agree on a coin toss and let that bug pass.
    attempts = 20
    recorder = _recorder_at(1, record_store, payload_writer)
    assessment = build_assessment([scored_candidate(0.2)])

    records = [
        await recorder.record(
            assessment,
            purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
            policy_generation=POLICY_GENERATION,
            idempotency_key=uuid7(),
        )
        for _ in range(attempts)
    ]

    assert len({record.id for record in records}) == attempts
    assert len({record.payload_sampled for record in records}) == 1


async def test_sample_membership_survives_a_change_of_policy_generation(
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    # Drift detection compares generations on the same references. Keying the sample
    # on the generation would hand each one an independent draw, so two generations
    # would differ both by policy and by which references they kept evidence for.
    generations = 20
    recorder = _recorder_at(1, record_store, payload_writer)
    assessment = build_assessment([scored_candidate(0.2)])

    records = [
        await recorder.record(
            assessment,
            purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
            policy_generation=f"generation-{n}",
            idempotency_key=uuid7(),
        )
        for n in range(generations)
    ]

    assert len({record.payload_sampled for record in records}) == 1


async def test_interesting_assessment_is_flagged_when_also_sampled(
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    recorder = _recorder_at(0, record_store, payload_writer)

    record = await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.payload_sampled is True


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
        idempotency_key=uuid7(),
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

    attempt = uuid7()

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=attempt,
    )

    assert record.payload_state == AssessmentPayloadState.STORED
    assert record.payload_blob_url == f"assessments/{attempt}.json"
    assert payload_writer.calls == [attempt]


async def test_unscorable_candidate_stores_a_payload_despite_no_proposal(
    recorder: DeduplicationAssessmentRecorder,
    payload_writer: FakePayloadWriter,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.2), scored_candidate(unscorable_reason="no title", rank=2)]
    )

    attempt = uuid7()

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=attempt,
    )

    assert record.outcome == DeduplicationAssessmentOutcome.NO_PROPOSAL
    assert record.payload_state == AssessmentPayloadState.STORED
    assert payload_writer.calls == [attempt]


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
        idempotency_key=uuid7(),
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
        idempotency_key=uuid7(),
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
        idempotency_key=uuid7(),
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
        idempotency_key=uuid7(),
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
        idempotency_key=uuid7(),
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
        idempotency_key=uuid7(),
    )

    assert record.es_route_ran is False
    assert record.es_index_name is None


async def test_record_explains_the_searchability_decision(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    # es_route_ran says the route did not run; only the reason says why. Without it a
    # record cannot explain itself and the retrieval has to be run again to find out.
    assessment = build_assessment([], searchable=False, index_version=None)

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.input_searchability_reason == (
        assessment.candidate_selection.input_searchability.reason
    )


async def test_searchable_input_records_a_run_route_even_without_an_index_alias(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    # get_current_index_name returns None when no alias fronts the index, which
    # says nothing about whether the query was issued.
    assessment = build_assessment([], searchable=True, index_version=None)

    record = await recorder.record(
        assessment,
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.es_route_ran is True
    assert record.es_index_name is None


async def test_failed_payload_write_keeps_the_summary_record(
    record_store: FakeRecordStore,
) -> None:
    recorder = DeduplicationAssessmentRecorder(
        record_store=record_store,
        payload_writer=FakePayloadWriter(error=MinioBlobStorageError("bucket gone")),
        evidence_sample_rate_bits=None,
    )

    record = await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.payload_state == AssessmentPayloadState.FAILED
    assert record.payload_blob_url is None
    assert record.payload_reason is not None
    assert "bucket gone" in record.payload_reason
    assert record_store.records[record.id].payload_state == (
        AssessmentPayloadState.FAILED
    )


async def test_payload_is_stored_before_the_summary_row(
    recorder: DeduplicationAssessmentRecorder,
    events: list[str],
) -> None:
    # Inserting first and correcting afterwards cannot survive a crash: add() only
    # flushes, so a rollback takes the row and leaves the uploaded blob unreferenced.
    await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert events == ["payload", "add"]


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        pytest.param(None, AssessmentPayloadState.STORED, id="stored"),
        pytest.param(
            MinioBlobStorageError("bucket gone"),
            AssessmentPayloadState.FAILED,
            id="failed",
        ),
    ],
)
async def test_retained_payload_costs_one_insert_and_no_update(
    record_store: FakeRecordStore,
    error: Exception | None,
    expected_state: AssessmentPayloadState,
) -> None:
    # One write per assessment either way. A second round trip on every retained
    # assessment is the cost this ordering exists to avoid.
    recorder = DeduplicationAssessmentRecorder(
        record_store=record_store,
        payload_writer=FakePayloadWriter(error=error),
        evidence_sample_rate_bits=None,
    )

    record = await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.payload_state == expected_state
    assert len(record_store.added) == 1
    assert record_store.updates == []


async def test_stored_record_carries_no_payload_reason(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    # A stored payload that still explained itself as missing would send an operator
    # looking for a failure that did not happen.
    record = await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=uuid7(),
    )

    assert record.payload_state == AssessmentPayloadState.STORED
    assert record.payload_reason is None


async def test_blob_is_named_for_the_delivery_that_produced_it(
    recorder: DeduplicationAssessmentRecorder,
    payload_writer: FakePayloadWriter,
) -> None:
    # Named for the delivery rather than the record, so a retry after a failed
    # insert overwrites the same object instead of stranding another one.
    attempt = uuid7()

    record = await recorder.record(
        build_assessment([scored_candidate(0.95)]),
        purpose=DeduplicationAssessmentPurpose.DEDUPLICATION,
        policy_generation=POLICY_GENERATION,
        idempotency_key=attempt,
    )

    assert payload_writer.calls == [attempt]
    assert record.payload_blob_url == f"assessments/{attempt}.json"


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
        idempotency_key=uuid7(),
    )

    assert [c.reference_id for c in record.scored_candidates] == [
        s.candidate.reference_id for s in assessment.scored_candidates
    ]
    assert record.proposed_duplicate_of_id == assessment.proposed_duplicate_of_id
