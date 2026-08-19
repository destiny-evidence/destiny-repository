from collections.abc import Callable
from uuid import UUID, uuid7

import pytest

from app.core.config import DedupAssessmentRecordingConfig
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
PAYLOAD_BYTES = 48_000


class FakeRecordStore:
    """In-memory stand-in for the assessment record repository."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.records: dict[UUID, DeduplicationAssessmentRecord] = {}
        self.added: list[DeduplicationAssessmentRecord] = []
        self.events = events if events is not None else []
        self.fail_next_add = False

    async def add(
        self, record: DeduplicationAssessmentRecord
    ) -> DeduplicationAssessmentRecord:
        if self.fail_next_add:
            self.fail_next_add = False
            msg = "insert rolled back"
            raise RuntimeError(msg)
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

    async def add_or_find_by_idempotency_key(
        self, record: DeduplicationAssessmentRecord
    ) -> DeduplicationAssessmentRecord:
        return await self.add(record)


class FakePayloadWriter:
    """Payload writer that records its calls and can be made to fail."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.calls: list[UUID] = []
        self.events = events if events is not None else []
        self.size_bytes = PAYLOAD_BYTES
        self.error: Exception | None = None

    async def write(
        self, payload_id: UUID, assessment: DeduplicationAssessment
    ) -> StoredPayload:
        self.calls.append(payload_id)
        self.events.append("payload")
        if self.error:
            raise self.error
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
    outcome: DeduplicationAssessmentOutcome = (
        DeduplicationAssessmentOutcome.NO_PROPOSAL
    ),
    proposed_duplicate_of_id: UUID | None = None,
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
        proposed_duplicate_of_id=proposed_duplicate_of_id,
        threshold_clearing_candidate_ids=clearing,
        unscorable_candidate_ids=unscorable,
    )


def assessment_scoring(scores: list[float | None]) -> DeduplicationAssessment:
    """Build an assessment whose candidates scored as given; None is unscorable."""
    return build_assessment(
        [
            scored_candidate(
                score,
                rank=rank,
                unscorable_reason=None if score is not None else "no title",
            )
            for rank, score in enumerate(scores, start=1)
        ]
    )


async def record_assessment(
    recorder: DeduplicationAssessmentRecorder,
    assessment: DeduplicationAssessment,
    *,
    purpose: DeduplicationAssessmentPurpose = (
        DeduplicationAssessmentPurpose.DEDUPLICATION
    ),
    policy_generation: str = POLICY_GENERATION,
    idempotency_key: UUID | None = None,
) -> DeduplicationAssessmentRecord:
    """Record an assessment, defaulting everything the test does not care about."""
    return await recorder.record(
        assessment,
        purpose=purpose,
        policy_generation=policy_generation,
        idempotency_key=idempotency_key or uuid7(),
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
def make_recorder(
    record_store: FakeRecordStore, payload_writer: FakePayloadWriter
) -> Callable[..., DeduplicationAssessmentRecorder]:
    """Build a recorder over the shared fakes at a given evidence sample rate."""

    def _make(
        sample_rate_bits: int | None = None,
    ) -> DeduplicationAssessmentRecorder:
        return DeduplicationAssessmentRecorder(
            record_store=record_store,
            payload_writer=payload_writer,
            recording_config=DedupAssessmentRecordingConfig(
                evidence_sample_rate_bits=sample_rate_bits
            ),
        )

    return _make


@pytest.fixture
def recorder(
    make_recorder: Callable[..., DeduplicationAssessmentRecorder],
) -> DeduplicationAssessmentRecorder:
    return make_recorder()


def test_evidence_sampling_applies_the_configured_rate():
    # Per id rather than one id: with the mask off by one, a single draw still
    # passes half the time.
    reference_ids = [uuid7() for _ in range(200)]

    assert not any(evidence_sampled(rid, None) for rid in reference_ids)
    assert all(evidence_sampled(rid, 0) for rid in reference_ids)

    selected = [rid for rid in reference_ids if evidence_sampled(rid, 3)]
    assert 0 < len(selected) < len(reference_ids)


@pytest.mark.parametrize(
    ("scores", "sample_rate_bits", "expected_state", "expected_sampled"),
    [
        pytest.param(
            [0.2], None, AssessmentPayloadState.NOT_RETAINED, False, id="dull"
        ),
        pytest.param([0.2], 0, AssessmentPayloadState.STORED, True, id="dull-sampled"),
        pytest.param([0.95], None, AssessmentPayloadState.STORED, False, id="cleared"),
        pytest.param(
            [0.2, None], None, AssessmentPayloadState.STORED, False, id="unscorable"
        ),
    ],
)
async def test_payload_is_retained_when_interesting_or_sampled(
    make_recorder: Callable[..., DeduplicationAssessmentRecorder],
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
    scores: list[float | None],
    sample_rate_bits: int | None,
    expected_state: AssessmentPayloadState,
    expected_sampled: bool,  # noqa: FBT001
) -> None:
    # The flag marks sample membership, not the reason a payload exists. Folding the
    # two together would hide sampled-and-interesting records and bias the sample.
    recorder = make_recorder(sample_rate_bits)
    attempt = uuid7()
    retained = expected_state is AssessmentPayloadState.STORED

    record = await record_assessment(
        recorder, assessment_scoring(scores), idempotency_key=attempt
    )

    assert record.payload_state == expected_state
    assert record.payload_sampled is expected_sampled
    assert record.payload_blob_url == (
        f"assessments/{attempt}.json" if retained else None
    )
    assert record.payload_bytes == (PAYLOAD_BYTES if retained else None)
    # A stored payload that still explained itself as missing would send an operator
    # looking for a failure that did not happen.
    assert record.payload_reason is None
    assert payload_writer.calls == ([attempt] if retained else [])
    # Coverage is why every assessment gets a row, retained payload or not.
    assert len(record_store.added) == 1


async def test_redelivered_attempt_writes_one_record_and_one_payload(
    make_recorder: Callable[..., DeduplicationAssessmentRecorder],
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    # A redelivered task must not double the population or the storage bill. The
    # attempt identifies the delivery, so the replay resolves to the first record.
    recorder = make_recorder(0)
    assessment = assessment_scoring([0.95])
    attempt = uuid7()

    first = await record_assessment(recorder, assessment, idempotency_key=attempt)
    second = await record_assessment(recorder, assessment, idempotency_key=attempt)

    assert second.id == first.id
    assert len(record_store.added) == 1
    assert payload_writer.calls == [attempt]


async def test_a_retried_delivery_reuses_the_payload_location(
    make_recorder: Callable[..., DeduplicationAssessmentRecorder],
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    # The find-first guard only sees committed rows, so a delivery whose insert
    # rolled back retries with nothing to find. Naming the payload for the delivery
    # rather than the record is what stops that retry stranding a second blob.
    recorder = make_recorder(0)
    assessment = assessment_scoring([0.95])
    attempt = uuid7()
    record_store.fail_next_add = True

    with pytest.raises(RuntimeError, match="insert rolled back"):
        await record_assessment(recorder, assessment, idempotency_key=attempt)
    retried = await record_assessment(recorder, assessment, idempotency_key=attempt)

    assert payload_writer.calls == [attempt, attempt]
    assert retried.payload_blob_url == f"assessments/{attempt}.json"


async def test_a_fresh_attempt_assesses_the_same_reference_again(
    make_recorder: Callable[..., DeduplicationAssessmentRecorder],
    record_store: FakeRecordStore,
) -> None:
    # Re-assessment under the same generation is legitimate: the corpus moves under a
    # stable configuration, so only the delivery is deduplicated, never the reference.
    recorder = make_recorder(0)
    assessment = assessment_scoring([0.95])

    first = await record_assessment(recorder, assessment)
    second = await record_assessment(recorder, assessment)

    assert second.id != first.id
    assert len(record_store.added) == 2


@pytest.mark.parametrize(
    "generations",
    [
        pytest.param([POLICY_GENERATION] * 20, id="within-a-generation"),
        pytest.param([f"generation-{n}" for n in range(20)], id="across-generations"),
    ],
)
async def test_sample_membership_follows_the_reference_alone(
    make_recorder: Callable[..., DeduplicationAssessmentRecorder],
    generations: list[str],
) -> None:
    # Twenty draws, not two: an independent draw per record would agree on a coin
    # toss half the time.
    recorder = make_recorder(1)
    assessment = assessment_scoring([0.2])

    records = [
        await record_assessment(recorder, assessment, policy_generation=generation)
        for generation in generations
    ]

    assert len({record.id for record in records}) == len(generations)
    assert len({record.payload_sampled for record in records}) == 1


@pytest.mark.parametrize(
    ("scores", "proposed_rank", "expected_best", "expected_best_non_winning"),
    [
        pytest.param([0.95, 0.44], 1, 0.95, 0.44, id="runner-up-behind-a-proposal"),
        pytest.param([0.44, 0.2], None, 0.44, 0.44, id="top-score-with-no-proposal"),
        pytest.param([], None, None, None, id="no-candidates"),
    ],
)
async def test_best_and_best_non_winning_scores_are_recorded(
    recorder: DeduplicationAssessmentRecorder,
    scores: list[float | None],
    proposed_rank: int | None,
    expected_best: float | None,
    expected_best_non_winning: float | None,
) -> None:
    # With no proposal every score is non-winning, so the margin field collapses to
    # the top score rather than going empty.
    pairs = [scored_candidate(score, rank=rank) for rank, score in enumerate(scores, 1)]
    proposed = pairs[proposed_rank - 1][0].reference_id if proposed_rank else None
    assessment = build_assessment(pairs, proposed_duplicate_of_id=proposed)

    record = await record_assessment(recorder, assessment)

    assert record.best_score == pytest.approx(expected_best)
    assert record.best_non_winning_score == pytest.approx(expected_best_non_winning)
    assert record.candidate_count == len(scores)


async def test_provenance_of_the_assessment_is_recorded(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    assessment = build_assessment(
        [scored_candidate(0.2)],
        outcome=DeduplicationAssessmentOutcome.PROPOSE_CANONICAL,
    )

    record = await record_assessment(
        recorder,
        assessment,
        purpose=DeduplicationAssessmentPurpose.PERFORMANCE_SHADOW,
    )

    assert record.purpose == DeduplicationAssessmentPurpose.PERFORMANCE_SHADOW
    assert record.outcome == DeduplicationAssessmentOutcome.PROPOSE_CANONICAL
    assert record.policy_generation == POLICY_GENERATION
    assert record.retrieval_policy == RetrievalPolicyName.CURRENT_FUZZY_V1
    assert record.k == 10
    assert record.candidate_count == 1
    assert record.deduper_version == "0.4.1"
    assert record.deduper_config_hash == "abc123"
    assert record.threshold == pytest.approx(0.8)
    assert record.incoming_reference_id == assessment.incoming_reference_id


@pytest.mark.parametrize(
    ("searchable", "index_version", "expected_ran"),
    [
        pytest.param(True, "reference-000042", True, id="searchable"),
        # get_current_index_name returns None when no alias fronts the index, which
        # says nothing about whether the query was issued.
        pytest.param(True, None, True, id="searchable-without-an-alias"),
        pytest.param(False, None, False, id="unsearchable"),
    ],
)
async def test_record_explains_whether_the_es_route_ran(
    recorder: DeduplicationAssessmentRecorder,
    searchable: bool,  # noqa: FBT001
    index_version: str | None,
    expected_ran: bool,  # noqa: FBT001
) -> None:
    # es_route_ran says the route did not run; only the reason says why. Without it a
    # record cannot explain itself and the retrieval has to be run again to find out.
    assessment = build_assessment(
        [], searchable=searchable, index_version=index_version
    )

    record = await record_assessment(recorder, assessment)

    assert record.es_route_ran is expected_ran
    assert record.es_index_name == index_version
    assert record.input_searchability_reason == (
        assessment.candidate_selection.input_searchability.reason
    )


async def test_failed_payload_write_keeps_the_summary_record(
    recorder: DeduplicationAssessmentRecorder,
    record_store: FakeRecordStore,
    payload_writer: FakePayloadWriter,
) -> None:
    payload_writer.error = MinioBlobStorageError("bucket gone")

    record = await record_assessment(recorder, assessment_scoring([0.95]))

    assert record.payload_state == AssessmentPayloadState.FAILED
    assert record.payload_blob_url is None
    assert record.payload_reason is not None
    assert "bucket gone" in record.payload_reason
    assert record_store.records[record.id].payload_state == (
        AssessmentPayloadState.FAILED
    )


async def test_payload_is_stored_before_a_single_summary_row(
    recorder: DeduplicationAssessmentRecorder,
    record_store: FakeRecordStore,
    events: list[str],
) -> None:
    # Inserting first and correcting afterwards cannot survive a crash: add() only
    # flushes, so a rollback takes the row and leaves the uploaded blob unreferenced.
    await record_assessment(recorder, assessment_scoring([0.95]))

    assert events == ["payload", "add"]
    assert len(record_store.added) == 1


async def test_scored_candidates_are_retained_on_the_record(
    recorder: DeduplicationAssessmentRecorder,
) -> None:
    pairs = [scored_candidate(0.95), scored_candidate(0.2, rank=2)]
    assessment = build_assessment(
        pairs, proposed_duplicate_of_id=pairs[0][0].reference_id
    )

    record = await record_assessment(recorder, assessment)

    assert [c.reference_id for c in record.scored_candidates] == [
        s.candidate.reference_id for s in assessment.scored_candidates
    ]
    assert record.proposed_duplicate_of_id == assessment.proposed_duplicate_of_id
