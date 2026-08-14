"""Run read-only deduplication assessments over a supplied JSONL blob."""

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum, auto
from io import BytesIO
from json import JSONDecodeError
from typing import Literal, Protocol, cast
from uuid import UUID, uuid7

import destiny_sdk
from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import (
    DeduplicationError,
    EvaluationConfigurationMismatchError,
)
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    CandidateIdentifier,
    CandidateRoute,
    CandidateSelectionInput,
    DeduperMetadata,
    DeduplicationAssessment,
    DeduplicationAssessmentOutcome,
    DeduplicationPairResult,
    Enhancement,
    LinkedExternalIdentifier,
    Reference,
    RetrievalPolicyName,
)
from app.persistence.blob.models import BlobStorageFile
from app.persistence.blob.repository import BlobRepository

logger = get_logger(__name__)


class EvaluationRecordStatus(StrEnum):
    """Status of one non-blank input line."""

    ASSESSED = auto()
    INPUT_INVALID = auto()
    EVALUATION_FAILED = auto()


class EvaluationInputReference(BaseModel):
    """Bibliographic fields frozen into one evaluation row."""

    title: str | None
    authors: list[str]
    year: int | None


class EvaluationInputRecord(BaseModel):
    """Dataset fields needed for one assessment."""

    query_id: str
    input_reference: EvaluationInputReference
    input_identifiers: list[str]
    route_applicability: list[Literal["identifier", "fuzzy"]]
    """Analysis label for the row; deliberately does not shape the candidate query."""
    excluded_reference_ids: list[UUID] = Field(default_factory=list, max_length=1)
    dataset_version: str

    model_config = ConfigDict(extra="allow")


class EvaluationRecordError(BaseModel):
    """Stable code and reviewable detail for one failed record."""

    code: Literal["invalid_json", "invalid_record", "evaluation_failed"]
    message: str


class EvaluationRecordResult(BaseModel):
    """Assessment or structured failure for one input line."""

    run_id: UUID
    query_id: str | None
    line_number: int
    status: EvaluationRecordStatus
    incoming_reference_id: UUID | None = None
    assessment: DeduplicationAssessment | None = None
    error: EvaluationRecordError | None = None


class EvaluationPairResult(BaseModel):
    """Analysis row projected from one assessed candidate."""

    run_id: UUID
    query_id: str
    line_number: int
    incoming_reference_id: UUID
    candidate_reference_id: UUID
    retrieval_rank: int
    retrieval_routes: list[CandidateRoute]
    pair_result: DeduplicationPairResult
    threshold: float
    clears_threshold: bool | None


class EvaluationRunConfiguration(BaseModel):
    """Dataset, corpus, retrieval and scorer identity for one run."""

    dataset_version: str
    environment: str
    corpus_observed_at: datetime
    elasticsearch_index_version: str
    code_commit: str
    retrieval_policy: RetrievalPolicyName
    k: int = Field(ge=1)
    deduper: DeduperMetadata


class EvaluationRunArtifacts(BaseModel):
    """Files and immutable input identity produced by a completed run."""

    run_id: UUID
    input_file: BlobStorageFile
    input_byte_size: int
    input_sha256: str
    record_results_file: BlobStorageFile
    pair_results_file: BlobStorageFile
    summary_file: BlobStorageFile
    manifest_file: BlobStorageFile


class SuppliedReferenceAssessor(Protocol):
    """Read-only supplied-reference assessment operation used by the runner."""

    async def evaluate_supplied(
        self,
        incoming: Reference,
        selection_input: CandidateSelectionInput,
        *,
        retrieval_policy: RetrievalPolicyName | None = None,
        k: int | None = None,
    ) -> DeduplicationAssessment:
        """
        Assess one supplied reference without writing repository state.

        :raises DeduplicationError: If this record cannot be assessed.
        """
        ...


class DeduplicationEvaluationRunner:
    """Assess supplied records and write a reviewable artifact bundle."""

    def __init__(self, *, assessor: SuppliedReferenceAssessor) -> None:
        """Keep the read-only assessor used by each record."""
        self._assessor = assessor

    async def run(
        self,
        *,
        run_id: UUID,
        input_file: BlobStorageFile,
        blob_repository: BlobRepository,
        configuration: EvaluationRunConfiguration,
    ) -> EvaluationRunArtifacts:
        """Evaluate a JSONL blob and write its run-scoped artifact bundle."""
        # Two passes over the immutable input: the manifest digest must cover the
        # exact bytes, which the line reader cannot yield once it has decoded them.
        digest = hashlib.sha256()
        byte_size = 0
        async for chunk in blob_repository.stream_chunks_from_blob_storage(input_file):
            digest.update(chunk)
            byte_size += len(chunk)

        path = f"deduplication_evaluation/{run_id}"
        record_results: list[EvaluationRecordResult] = []
        line_number = 0
        try:
            async with blob_repository.stream_file_from_blob_storage(
                input_file
            ) as lines:
                async for line in lines:
                    line_number += 1
                    if not line.strip():
                        continue
                    record_results.append(
                        await self._evaluate_line(
                            run_id=run_id,
                            line=line,
                            line_number=line_number,
                            configuration=configuration,
                        )
                    )
        except Exception:
            # A run costs hours of retrieval, so keep whatever completed. Writing no
            # manifest is what marks the bundle incomplete.
            await self._upload(
                blob_repository,
                path,
                "record-results.jsonl",
                self._jsonl(record_results),
            )
            raise

        pair_results = [
            pair
            for record_result in record_results
            for pair in self._pair_results(record_result)
        ]
        input_sha256 = digest.hexdigest()

        record_bytes = self._jsonl(record_results)
        record_file = await self._upload(
            blob_repository, path, "record-results.jsonl", record_bytes
        )
        pair_bytes = self._jsonl(pair_results)
        pair_file = await self._upload(
            blob_repository, path, "pair-results.jsonl", pair_bytes
        )
        summary_bytes = self._summary(
            run_id=run_id,
            input_file=input_file,
            input_byte_size=byte_size,
            input_sha256=input_sha256,
            records=record_results,
            pairs=pair_results,
        ).encode()
        summary_file = await self._upload(
            blob_repository, path, "summary.md", summary_bytes
        )

        status_counts = Counter(result.status for result in record_results)
        manifest = {
            "schema_version": "deduplication-evaluation-manifest/v1",
            "run_id": str(run_id),
            "input": {
                "uri": input_file.to_uri(),
                "dataset_version": configuration.dataset_version,
                "byte_size": byte_size,
                "sha256": input_sha256,
            },
            "configuration": configuration.model_dump(mode="json"),
            "counts": {
                "record_statuses": {
                    status.value: status_counts[status]
                    for status in EvaluationRecordStatus
                },
                "pair_rows": len(pair_results),
            },
            "artifacts": {
                "record-results.jsonl": self._artifact(
                    record_file, record_bytes, "evaluation-record-result/v1"
                ),
                "pair-results.jsonl": self._artifact(
                    pair_file, pair_bytes, "evaluation-pair-result/v1"
                ),
                "summary.md": self._artifact(
                    summary_file,
                    summary_bytes,
                    "deduplication-evaluation-summary/v1",
                ),
            },
        }
        manifest_file = await self._upload(
            blob_repository,
            path,
            "manifest.json",
            json.dumps(manifest, indent=2).encode(),
        )
        return EvaluationRunArtifacts(
            run_id=run_id,
            input_file=input_file,
            input_byte_size=byte_size,
            input_sha256=input_sha256,
            record_results_file=record_file,
            pair_results_file=pair_file,
            summary_file=summary_file,
            manifest_file=manifest_file,
        )

    async def _evaluate_line(
        self,
        *,
        run_id: UUID,
        line: str,
        line_number: int,
        configuration: EvaluationRunConfiguration,
    ) -> EvaluationRecordResult:
        try:
            payload = json.loads(line)
        except JSONDecodeError as exc:
            return self._invalid_result(
                run_id,
                None,
                line_number,
                "invalid_json",
                f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.",
            )
        if not isinstance(payload, dict):
            return self._invalid_result(
                run_id,
                None,
                line_number,
                "invalid_record",
                "Invalid evaluation record: expected a JSON object.",
            )

        raw_query_id = payload.get("query_id")
        query_id = raw_query_id if isinstance(raw_query_id, str) else None
        try:
            record = EvaluationInputRecord.model_validate(payload)
            incoming, selection_input = self._assessment_inputs(record)
        except ValueError as exc:
            return self._invalid_result(
                run_id,
                query_id,
                line_number,
                "invalid_record",
                f"Invalid evaluation record: {exc}",
            )

        try:
            assessment = await self._assessor.evaluate_supplied(
                incoming,
                selection_input,
                retrieval_policy=configuration.retrieval_policy,
                k=configuration.k,
            )
        except DeduplicationError as exc:
            logger.exception(
                "Failed to assess supplied evaluation record",
                query_id=record.query_id,
                line_number=line_number,
            )
            return EvaluationRecordResult(
                run_id=run_id,
                query_id=record.query_id,
                line_number=line_number,
                status=EvaluationRecordStatus.EVALUATION_FAILED,
                incoming_reference_id=incoming.id,
                error=EvaluationRecordError(
                    code="evaluation_failed",
                    message=f"Evaluation failed ({type(exc).__name__}): {exc}",
                ),
            )
        self._verify_configuration(assessment, configuration, line_number)
        return EvaluationRecordResult(
            run_id=run_id,
            query_id=record.query_id,
            line_number=line_number,
            status=EvaluationRecordStatus.ASSESSED,
            incoming_reference_id=incoming.id,
            assessment=assessment,
        )

    @staticmethod
    def _verify_configuration(
        assessment: DeduplicationAssessment,
        configuration: EvaluationRunConfiguration,
        line_number: int,
    ) -> None:
        """Fail the run rather than publish a manifest the run contradicts."""
        selection = assessment.candidate_selection
        asserted: list[tuple[str, object, object]] = [
            (
                "retrieval_policy",
                configuration.retrieval_policy,
                selection.retrieval_policy,
            ),
            ("k", configuration.k, selection.k_requested),
            ("deduper", configuration.deduper, assessment.deduper),
        ]
        if selection.index_version is not None:
            # An absent index version means this record was never searched.
            asserted.append(
                (
                    "elasticsearch_index_version",
                    configuration.elasticsearch_index_version,
                    selection.index_version,
                )
            )
        mismatches = [
            f"{name} asserted {claimed!r}, ran {observed!r}"
            for name, claimed, observed in asserted
            if claimed != observed
        ]
        if mismatches:
            msg = (
                f"Evaluation run contradicts its configuration at line {line_number}: "
                + "; ".join(mismatches)
            )
            raise EvaluationConfigurationMismatchError(msg)

    @staticmethod
    def _invalid_result(
        run_id: UUID,
        query_id: str | None,
        line_number: int,
        code: Literal["invalid_json", "invalid_record"],
        message: str,
    ) -> EvaluationRecordResult:
        return EvaluationRecordResult(
            run_id=run_id,
            query_id=query_id,
            line_number=line_number,
            status=EvaluationRecordStatus.INPUT_INVALID,
            error=EvaluationRecordError(code=code, message=message),
        )

    @staticmethod
    def _pair_results(result: EvaluationRecordResult) -> list[EvaluationPairResult]:
        if result.assessment is None:
            return []
        return [
            EvaluationPairResult(
                run_id=result.run_id,
                query_id=cast(str, result.query_id),
                line_number=result.line_number,
                incoming_reference_id=cast(UUID, result.incoming_reference_id),
                candidate_reference_id=scored.candidate.reference_id,
                retrieval_rank=scored.candidate.rank,
                retrieval_routes=scored.candidate.routes,
                pair_result=scored.pair_result,
                threshold=result.assessment.deduper.threshold,
                clears_threshold=scored.clears_threshold,
            )
            for scored in result.assessment.scored_candidates
        ]

    @staticmethod
    def _assessment_inputs(
        record: EvaluationInputRecord,
    ) -> tuple[Reference, CandidateSelectionInput]:
        reference_id = uuid7()
        identifiers = [
            destiny_sdk.identifiers.ExternalIdentifierAdapter.validate_python(
                destiny_sdk.identifiers.IdentifierLookup.parse(value).model_dump()
            )
            for value in record.input_identifiers
        ]
        last_author = len(record.input_reference.authors) - 1
        authorship = [
            destiny_sdk.enhancements.Authorship(
                display_name=name,
                position=(
                    destiny_sdk.enhancements.AuthorPosition.FIRST
                    if index == 0
                    else (
                        destiny_sdk.enhancements.AuthorPosition.LAST
                        if index == last_author
                        else destiny_sdk.enhancements.AuthorPosition.MIDDLE
                    )
                ),
            )
            for index, name in enumerate(record.input_reference.authors)
        ]
        incoming = Reference(
            id=reference_id,
            identifiers=[
                LinkedExternalIdentifier(
                    identifier=identifier, reference_id=reference_id
                )
                for identifier in identifiers
            ],
            enhancements=[
                Enhancement(
                    reference_id=reference_id,
                    source=record.dataset_version,
                    visibility=destiny_sdk.visibility.Visibility.PUBLIC,
                    content=destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                        title=record.input_reference.title,
                        authorship=authorship,
                        publication_year=record.input_reference.year,
                    ),
                )
            ],
        )
        selection_input = CandidateSelectionInput(
            title=record.input_reference.title,
            authors=record.input_reference.authors,
            publication_year=record.input_reference.year,
            identifiers=[
                CandidateIdentifier.from_specific(item) for item in identifiers
            ],
            excluded_reference_id=(
                record.excluded_reference_ids[0]
                if record.excluded_reference_ids
                else None
            ),
        )
        return incoming, selection_input

    @staticmethod
    def _jsonl(rows: Sequence[BaseModel]) -> bytes:
        return "".join(f"{row.model_dump_json()}\n" for row in rows).encode()

    @staticmethod
    async def _upload(
        repository: BlobRepository,
        path: str,
        filename: str,
        content: bytes,
    ) -> BlobStorageFile:
        return await repository.upload_file_to_blob_storage(
            content=BytesIO(content),
            path=path,
            filename=filename,
            content_type=(
                "text/markdown"
                if filename.endswith(".md")
                else "application/jsonl"
                if filename.endswith(".jsonl")
                else "application/json"
            ),
        )

    @staticmethod
    def _artifact(
        file: BlobStorageFile, content: bytes, schema_version: str
    ) -> dict[str, str | int]:
        return {
            "uri": file.to_uri(),
            "schema_version": schema_version,
            "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    @staticmethod
    def _summary(  # noqa: PLR0913
        *,
        run_id: UUID,
        input_file: BlobStorageFile,
        input_byte_size: int,
        input_sha256: str,
        records: Sequence[EvaluationRecordResult],
        pairs: Sequence[EvaluationPairResult],
    ) -> str:
        statuses = Counter(result.status for result in records)
        outcomes = Counter(
            result.assessment.outcome
            for result in records
            if result.assessment is not None
        )
        clears = sum(pair.clears_threshold is True for pair in pairs)
        below = sum(pair.clears_threshold is False for pair in pairs)
        unscorable = sum(pair.clears_threshold is None for pair in pairs)
        return (
            "# Deduplication evaluation summary\n\n"
            f"Run ID: `{run_id}`\n\n"
            f"Input: `{input_file.to_uri()}`\n\n"
            f"Input bytes: {input_byte_size}\n\n"
            f"Input SHA-256: `{input_sha256}`\n\n"
            f"Records: {len(records)}\n\n"
            f"Assessed records: {statuses[EvaluationRecordStatus.ASSESSED]}\n\n"
            "Invalid input records: "
            f"{statuses[EvaluationRecordStatus.INPUT_INVALID]}\n\n"
            "Evaluation-failed records: "
            f"{statuses[EvaluationRecordStatus.EVALUATION_FAILED]}\n\n"
            f"Pair rows: {len(pairs)}\n\n"
            "## Assessment outcomes\n\n"
            "- `propose_canonical`: "
            f"{outcomes[DeduplicationAssessmentOutcome.PROPOSE_CANONICAL]}\n"
            "- `propose_duplicate`: "
            f"{outcomes[DeduplicationAssessmentOutcome.PROPOSE_DUPLICATE]}\n"
            "- `no_proposal`: "
            f"{outcomes[DeduplicationAssessmentOutcome.NO_PROPOSAL]}\n\n"
            "## Pair evidence\n\n"
            f"- Clears threshold: {clears}\n"
            f"- Below threshold: {below}\n"
            f"- Unscorable: {unscorable}\n"
        )
