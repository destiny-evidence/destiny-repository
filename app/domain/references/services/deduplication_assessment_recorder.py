"""Durable recording of deduplication assessments, with no decision writing."""

import hashlib
from io import BytesIO
from typing import NamedTuple, Protocol
from uuid import UUID, uuid7

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

# The summary row is written before the payload, so a payload that is wanted but not
# yet stored reads as failed. A crash then leaves the truth rather than a stuck state.
PAYLOAD_PENDING_REASON = "Payload write not completed."
PAYLOAD_PATH = "deduplication-assessments"


def evidence_sampled(record_id: UUID, sample_rate_bits: int | None) -> bool:
    """
    Whether this record is in the 1 / (2 ** sample_rate_bits) evidence sample.

    Keyed on the record rather than drawn at random, so a retried or replayed
    assessment decides the same way and a run can be reproduced.
    """
    if sample_rate_bits is None:
        return False
    # Hashed rather than read off the id: uuid7 carries a monotonic counter in its
    # random field, so using those bits directly risks selecting whole batches at once.
    digest = hashlib.blake2b(record_id.bytes, digest_size=8).digest()
    mask = (1 << sample_rate_bits) - 1
    return int.from_bytes(digest) & mask == 0


class AssessmentRecordStore(Protocol):
    """Persistence required to record an assessment."""

    async def add(
        self, record: DeduplicationAssessmentRecord
    ) -> DeduplicationAssessmentRecord:
        """Persist a new assessment record."""
        ...

    async def update_by_pk(
        self, pk: UUID, **kwargs: object
    ) -> DeduplicationAssessmentRecord:
        """Update an existing assessment record in place."""
        ...


class StoredPayload(NamedTuple):
    """Where an evidence payload was stored, and how much it cost to store."""

    location: str
    size_bytes: int


class AssessmentPayloadWriter(Protocol):
    """Writer for the full evidence payload behind an assessment."""

    async def write(
        self, record_id: UUID, assessment: DeduplicationAssessment
    ) -> StoredPayload:
        """Store the payload and return where it went and how large it was."""
        ...


class BlobAssessmentPayloadWriter:
    """Write assessment payloads to the team blob container."""

    def __init__(self, *, blob_repository: BlobRepository) -> None:
        """Initialize the writer with the blob repository it uploads through."""
        self._blob_repository = blob_repository

    async def write(
        self, record_id: UUID, assessment: DeduplicationAssessment
    ) -> StoredPayload:
        """Store the payload under the record it belongs to."""
        content = assessment.model_dump_json().encode()
        # Named for the record rather than the reference: a reference can be assessed
        # many times, and a uuid7 filename sorts by creation.
        file = await self._blob_repository.upload_file_to_blob_storage(
            content=BytesIO(content),
            path=PAYLOAD_PATH,
            filename=f"{record_id}.json",
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

    async def record(
        self,
        assessment: DeduplicationAssessment,
        *,
        purpose: DeduplicationAssessmentPurpose,
        policy_generation: str,
    ) -> DeduplicationAssessmentRecord:
        """Persist an assessment summary, and its payload when worth keeping."""
        selection = assessment.candidate_selection
        best_score, best_non_winning_score = self._scores(assessment)
        # The id is minted here rather than by the model, because sampling keys off it
        # and the flag has to be set on the row as it is inserted.
        record_id = uuid7()
        sampled = evidence_sampled(record_id, self._evidence_sample_rate_bits)
        retain_payload = self._is_interesting(assessment) or sampled

        record = await self._record_store.add(
            DeduplicationAssessmentRecord(
                id=record_id,
                incoming_reference_id=assessment.incoming_reference_id,
                purpose=purpose,
                policy_generation=policy_generation,
                retrieval_policy=selection.retrieval_policy,
                k=selection.k_requested,
                candidate_count=selection.diagnostics.candidate_count,
                # The index name is null without an alias, so it cannot stand in.
                es_route_ran=selection.input_searchability.searchable,
                es_index_name=selection.index_version,
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
                payload_state=AssessmentPayloadState.FAILED
                if retain_payload
                else AssessmentPayloadState.NOT_RETAINED,
                payload_reason=PAYLOAD_PENDING_REASON if retain_payload else None,
                payload_sampled=sampled,
            )
        )
        if not retain_payload:
            return record

        try:
            stored = await self._payload_writer.write(
                record_id=record_id, assessment=assessment
            )
        except BlobStorageError as exc:
            # Coverage is why every assessment gets a row, so a storage failure must
            # not remove one. The summary stands and says the payload is missing.
            return await self._record_store.update_by_pk(
                record_id, payload_reason=str(exc)
            )

        return await self._record_store.update_by_pk(
            record_id,
            payload_state=AssessmentPayloadState.STORED,
            payload_blob_url=stored.location,
            payload_bytes=stored.size_bytes,
            payload_reason=None,
        )
