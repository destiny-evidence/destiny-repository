"""Durable recording of deduplication assessments, with no decision writing."""

import hashlib
from io import BytesIO
from typing import NamedTuple, Protocol
from uuid import UUID

from app.core.config import EVIDENCE_SAMPLE_DIGEST_BITS
from app.core.exceptions import BlobStorageError
from app.domain.references.models.models import (
    AssessmentCandidateSummary,
    AssessmentPayloadState,
    DeduplicationAssessment,
    DeduplicationAssessmentPurpose,
    DeduplicationAssessmentRecord,
)
from app.persistence.blob.models import BlobContainer
from app.persistence.blob.repository import BlobRepository

PAYLOAD_PATH = "deduplication-assessments"


def evidence_sampled(
    incoming_reference_id: UUID,
    sample_rate_bits: int | None,
) -> bool:
    """
    Whether this assessment is in the 1 / (2 ** sample_rate_bits) evidence sample.

    Keyed on the reference alone, so every policy generation keeps evidence for the
    same references and two generations can be compared on like for like.
    """
    if sample_rate_bits is None:
        return False
    if not 0 <= sample_rate_bits <= EVIDENCE_SAMPLE_DIGEST_BITS:
        msg = (
            f"Sample rate must be 0 to {EVIDENCE_SAMPLE_DIGEST_BITS}, the digest width."
        )
        raise ValueError(msg)
    # Hashed rather than read off the reference id: uuid7 carries a monotonic counter
    # in its random field, so those bits select whole ingest batches at once.
    digest = hashlib.blake2b(
        incoming_reference_id.bytes, digest_size=EVIDENCE_SAMPLE_DIGEST_BITS // 8
    ).digest()
    mask = (1 << sample_rate_bits) - 1
    return int.from_bytes(digest) & mask == 0


class AssessmentRecordStore(Protocol):
    """Persistence required to record an assessment."""

    async def add(
        self, record: DeduplicationAssessmentRecord
    ) -> DeduplicationAssessmentRecord:
        """Persist a new assessment record."""
        ...

    async def find(self, **filters: object) -> list[DeduplicationAssessmentRecord]:
        """Return the records matching the given field filters."""
        ...


class StoredPayload(NamedTuple):
    """Where an evidence payload was stored, and how much it cost to store."""

    location: str
    size_bytes: int


class _PayloadOutcome(NamedTuple):
    """The payload fields of a record, once the payload's fate is settled."""

    state: AssessmentPayloadState
    location: str | None = None
    size_bytes: int | None = None
    reason: str | None = None


class AssessmentPayloadWriter(Protocol):
    """Writer for the full evidence payload behind an assessment."""

    async def write(
        self, payload_id: UUID, assessment: DeduplicationAssessment
    ) -> StoredPayload:
        """Store the payload and return where it went and how large it was."""
        ...


class BlobAssessmentPayloadWriter:
    """Write assessment payloads to the team blob container."""

    def __init__(self, *, blob_repository: BlobRepository) -> None:
        """Initialize the writer with the blob repository it uploads through."""
        self._blob_repository = blob_repository

    async def write(
        self, payload_id: UUID, assessment: DeduplicationAssessment
    ) -> StoredPayload:
        """Store the payload under the delivery it belongs to."""
        content = assessment.model_dump_json().encode()
        file = await self._blob_repository.upload_file_to_blob_storage(
            content=BytesIO(content),
            path=PAYLOAD_PATH,
            filename=f"{payload_id}.json",
            container=BlobContainer.OPERATIONS,
        )
        return StoredPayload(location=file.to_uri(), size_bytes=len(content))


class DeduplicationAssessmentRecorder:
    """Record assessments without any ability to write a duplicate decision."""

    def __init__(
        self,
        *,
        record_store: AssessmentRecordStore,
        payload_writer: AssessmentPayloadWriter,
        evidence_sample_rate_bits: int | None,
    ) -> None:
        """Initialize the recorder with its persistence collaborators."""
        self._record_store = record_store
        self._payload_writer = payload_writer
        self._evidence_sample_rate_bits = evidence_sample_rate_bits

    @staticmethod
    def _is_interesting(assessment: DeduplicationAssessment) -> bool:
        """Whether a later reader would need this assessment's evidence."""
        return bool(
            assessment.threshold_clearing_candidate_ids
            or assessment.unscorable_candidate_ids
        )

    @staticmethod
    def _scores(
        assessment: DeduplicationAssessment,
    ) -> tuple[float | None, float | None]:
        """Return the best score and the best score that did not win."""
        probabilities = [
            scored.pair_result.probability
            for scored in assessment.scored_candidates
            if scored.pair_result.probability is not None
        ]
        # With no proposal every score is non-winning, so this collapses to the top
        # score and one field carries the margin in both cases.
        non_winning = [
            scored.pair_result.probability
            for scored in assessment.scored_candidates
            if scored.pair_result.probability is not None
            and scored.candidate.reference_id != assessment.proposed_duplicate_of_id
        ]
        return max(probabilities, default=None), max(non_winning, default=None)

    async def _store_payload(
        self, payload_id: UUID, assessment: DeduplicationAssessment
    ) -> _PayloadOutcome:
        """Write the payload, reporting a storage failure rather than raising."""
        try:
            stored = await self._payload_writer.write(
                payload_id=payload_id, assessment=assessment
            )
        except BlobStorageError as exc:
            # Coverage is why every assessment gets a row, so a storage failure must
            # not cost one. The summary stands and says the payload is missing.
            return _PayloadOutcome(AssessmentPayloadState.FAILED, reason=str(exc))
        return _PayloadOutcome(
            AssessmentPayloadState.STORED,
            location=stored.location,
            size_bytes=stored.size_bytes,
        )

    async def record(
        self,
        assessment: DeduplicationAssessment,
        *,
        purpose: DeduplicationAssessmentPurpose,
        policy_generation: str,
        idempotency_key: UUID,
    ) -> DeduplicationAssessmentRecord:
        """Persist an assessment summary, and its payload when worth keeping."""
        # Identifies the delivery, not the reference: the same reference is legitimately
        # reassessed under one generation as the corpus moves beneath it.
        existing = await self._record_store.find(idempotency_key=idempotency_key)
        if existing:
            return existing[0]

        selection = assessment.candidate_selection
        best_score, best_non_winning_score = self._scores(assessment)
        sampled = evidence_sampled(
            assessment.incoming_reference_id, self._evidence_sample_rate_bits
        )
        retain_payload = self._is_interesting(assessment) or sampled

        # Named for the delivery, not the record: the find-first guard above only sees
        # committed rows, so a retry after a rolled-back insert would otherwise mint a
        # fresh record id and strand a second copy of the same payload.
        payload = (
            await self._store_payload(idempotency_key, assessment)
            if retain_payload
            else _PayloadOutcome(AssessmentPayloadState.NOT_RETAINED)
        )

        return await self._record_store.add(
            DeduplicationAssessmentRecord(
                idempotency_key=idempotency_key,
                incoming_reference_id=assessment.incoming_reference_id,
                purpose=purpose,
                policy_generation=policy_generation,
                retrieval_policy=selection.retrieval_policy,
                k=selection.k_requested,
                candidate_count=selection.diagnostics.candidate_count,
                # The index name is null without an alias, so it cannot stand in.
                es_route_ran=selection.input_searchability.searchable,
                es_index_name=selection.index_version,
                input_searchability_reason=selection.input_searchability.reason,
                deduper_version=assessment.deduper.package_version,
                deduper_config_hash=assessment.deduper.configuration_hash,
                threshold=assessment.deduper.threshold,
                outcome=assessment.outcome,
                proposed_duplicate_of_id=assessment.proposed_duplicate_of_id,
                best_score=best_score,
                best_non_winning_score=best_non_winning_score,
                scored_candidates=[
                    AssessmentCandidateSummary.from_scored_candidate(scored)
                    for scored in assessment.scored_candidates
                ],
                payload_state=payload.state,
                payload_blob_url=payload.location,
                payload_bytes=payload.size_bytes,
                payload_reason=payload.reason,
                payload_sampled=sampled,
            )
        )
