"""Run read-only deduplication assessments over supplied evaluation records."""

import codecs
import hashlib
import json
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from enum import StrEnum, auto
from io import BytesIO
from json import JSONDecodeError
from typing import Literal, Protocol, cast
from uuid import UUID, uuid7

import destiny_sdk
from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import DeduplicationError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    CandidateIdentifier,
    CandidateRoute,
    CandidateSelectionInput,
    DeduplicationAssessment,
    DeduplicationPairResult,
    RetrievalPolicyName,
)
from app.persistence.blob.models import BlobStorageFile
from app.persistence.blob.repository import BlobRepository

logger = get_logger(__name__)


class EvaluationRecordStatus(StrEnum):
    """Result status for one non-blank evaluation input line."""

    ASSESSED = auto()
    INPUT_INVALID = auto()
    EVALUATION_FAILED = auto()


class EvaluationInputReference(BaseModel):
    """Bibliographic fields frozen into one retrieval-evaluation row."""

    title: str | None
    authors: list[str]
    year: int | None


class EvaluationInputRecord(BaseModel):
    """Fields needed to assess one retrieval-evaluation dataset row."""

    query_id: str
    input_reference: EvaluationInputReference
    input_identifiers: list[str]
    route_applicability: list[Literal["identifier", "fuzzy"]]
    excluded_reference_ids: list[UUID] = Field(default_factory=list, max_length=1)
    dataset_version: str

    model_config = ConfigDict(extra="allow")


class EvaluationRecordError(BaseModel):
    """Stable machine code and reviewable detail for one failed record."""

    code: Literal["invalid_json", "invalid_record", "evaluation_failed"]
    message: str


class EvaluationRecordResult(BaseModel):
    """Assessment or structured failure for one non-blank input line."""

    run_id: UUID
    query_id: str | None
    line_number: int
    status: EvaluationRecordStatus
    incoming_reference_id: UUID | None = None
    assessment: DeduplicationAssessment | None = None
    error: EvaluationRecordError | None = None


class EvaluationPairResult(BaseModel):
    """One analysis-friendly row projected from an assessment candidate."""

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


class EvaluationRunArtifacts(BaseModel):
    """Run-scoped artifacts written before the completion manifest."""

    run_id: UUID
    input_file: BlobStorageFile
    input_byte_size: int
    input_sha256: str
    record_results_file: BlobStorageFile
    pair_results_file: BlobStorageFile
    summary_file: BlobStorageFile


class SuppliedReferenceAssessor(Protocol):
    """Read-only supplied-reference assessment operation used by the runner."""

    async def evaluate_supplied(
        self,
        incoming: destiny_sdk.references.Reference,
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
    """Convert supplied records and pass them to the read-only assessor."""

    def __init__(self, *, assessor: SuppliedReferenceAssessor) -> None:
        """Initialize the runner with its read-only assessment dependency."""
        self._assessor = assessor

    @staticmethod
    def project_pair_results(
        result: EvaluationRecordResult,
    ) -> list[EvaluationPairResult]:
        """Project analysis rows from one completed record assessment."""
        if result.status is not EvaluationRecordStatus.ASSESSED:
            return []
        assessment = cast(DeduplicationAssessment, result.assessment)
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
                threshold=assessment.deduper.threshold,
                clears_threshold=scored.clears_threshold,
            )
            for scored in assessment.scored_candidates
        ]

    async def run(
        self,
        *,
        run_id: UUID,
        input_file: BlobStorageFile,
        blob_repository: BlobRepository,
        retrieval_policy: RetrievalPolicyName,
        k: int,
    ) -> EvaluationRunArtifacts:
        """Evaluate an immutable JSONL blob and write run-scoped artifacts."""
        hasher = hashlib.sha256()
        input_byte_size = 0
        decoder = codecs.getincrementaldecoder("utf-8")()

        async def input_lines() -> AsyncIterator[str]:
            nonlocal input_byte_size
            buffer = ""
            async for chunk in blob_repository.stream_chunks_from_blob_storage(
                input_file
            ):
                hasher.update(chunk)
                input_byte_size += len(chunk)
                buffer += decoder.decode(chunk)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    yield line
            buffer += decoder.decode(b"", final=True)
            if buffer:
                yield buffer

        record_results = [
            result
            async for result in self.evaluate_lines(
                run_id=run_id,
                lines=input_lines(),
                retrieval_policy=retrieval_policy,
                k=k,
            )
        ]
        pair_results = [
            pair
            for record_result in record_results
            for pair in self.project_pair_results(record_result)
        ]
        path = f"deduplication_evaluation/{run_id}"
        record_results_file = await blob_repository.upload_file_to_blob_storage(
            content=self._jsonl_buffer(record_results),
            path=path,
            filename="record-results.jsonl",
            content_type="application/jsonl",
        )
        pair_results_file = await blob_repository.upload_file_to_blob_storage(
            content=self._jsonl_buffer(pair_results),
            path=path,
            filename="pair-results.jsonl",
            content_type="application/jsonl",
        )
        summary_file = await blob_repository.upload_file_to_blob_storage(
            content=BytesIO(
                self._summary(
                    run_id=run_id,
                    input_details=(
                        input_file,
                        input_byte_size,
                        hasher.hexdigest(),
                    ),
                    record_results=record_results,
                    pair_count=len(pair_results),
                ).encode()
            ),
            path=path,
            filename="summary.md",
            content_type="text/markdown",
        )
        return EvaluationRunArtifacts(
            run_id=run_id,
            input_file=input_file,
            input_byte_size=input_byte_size,
            input_sha256=hasher.hexdigest(),
            record_results_file=record_results_file,
            pair_results_file=pair_results_file,
            summary_file=summary_file,
        )

    @staticmethod
    def _jsonl_buffer(rows: Sequence[BaseModel]) -> BytesIO:
        """Serialize model rows as newline-terminated JSONL bytes."""
        return BytesIO("".join(f"{row.model_dump_json()}\n" for row in rows).encode())

    @staticmethod
    def _summary(
        *,
        run_id: UUID,
        input_details: tuple[BlobStorageFile, int, str],
        record_results: Sequence[EvaluationRecordResult],
        pair_count: int,
    ) -> str:
        """Render the human-readable summary written before the manifest."""
        input_file, input_byte_size, input_sha256 = input_details
        status_counts = {
            status: sum(result.status is status for result in record_results)
            for status in EvaluationRecordStatus
        }
        return (
            "# Deduplication evaluation summary\n\n"
            f"Run ID: `{run_id}`\n\n"
            f"Input: `{input_file.to_uri()}`\n\n"
            f"Input bytes: {input_byte_size}\n\n"
            f"Input SHA-256: `{input_sha256}`\n\n"
            f"Records: {len(record_results)}\n\n"
            f"Assessed records: {status_counts[EvaluationRecordStatus.ASSESSED]}\n\n"
            "Invalid input records: "
            f"{status_counts[EvaluationRecordStatus.INPUT_INVALID]}\n\n"
            "Evaluation-failed records: "
            f"{status_counts[EvaluationRecordStatus.EVALUATION_FAILED]}\n\n"
            f"Pair rows: {pair_count}\n"
        )

    async def evaluate_lines(
        self,
        *,
        run_id: UUID,
        lines: AsyncIterable[str],
        retrieval_policy: RetrievalPolicyName,
        k: int,
    ) -> AsyncIterator[EvaluationRecordResult]:
        """Evaluate each non-blank line in physical input order."""
        line_number = 0
        async for line in lines:
            line_number += 1
            if line.strip():
                yield await self.evaluate_line(
                    run_id=run_id,
                    line=line,
                    line_number=line_number,
                    retrieval_policy=retrieval_policy,
                    k=k,
                )

    async def evaluate_line(
        self,
        *,
        run_id: UUID,
        line: str,
        line_number: int,
        retrieval_policy: RetrievalPolicyName,
        k: int,
    ) -> EvaluationRecordResult:
        """Evaluate one supplied JSONL record."""
        try:
            payload = json.loads(line)
        except JSONDecodeError as exc:
            return self._invalid_result(
                run_id=run_id,
                query_id=None,
                line_number=line_number,
                code="invalid_json",
                message=(
                    f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}."
                ),
            )

        if not isinstance(payload, dict):
            return self._invalid_result(
                run_id=run_id,
                query_id=None,
                line_number=line_number,
                code="invalid_record",
                message="Invalid evaluation record: expected a JSON object.",
            )

        raw_query_id = payload.get("query_id")
        query_id = raw_query_id if isinstance(raw_query_id, str) else None
        try:
            record = EvaluationInputRecord.model_validate(payload)
            incoming, selection_input = self._build_assessment_inputs(record)
        except ValueError as exc:
            return self._invalid_result(
                run_id=run_id,
                query_id=query_id,
                line_number=line_number,
                code="invalid_record",
                message=f"Invalid evaluation record: {exc}",
            )

        try:
            assessment = await self._assessor.evaluate_supplied(
                incoming,
                selection_input,
                retrieval_policy=retrieval_policy,
                k=k,
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
        return EvaluationRecordResult(
            run_id=run_id,
            query_id=record.query_id,
            line_number=line_number,
            status=EvaluationRecordStatus.ASSESSED,
            incoming_reference_id=incoming.id,
            assessment=assessment,
        )

    @staticmethod
    def _invalid_result(
        *,
        run_id: UUID,
        query_id: str | None,
        line_number: int,
        code: Literal["invalid_json", "invalid_record"],
        message: str,
    ) -> EvaluationRecordResult:
        """Build one input failure envelope without invoking the assessor."""
        return EvaluationRecordResult(
            run_id=run_id,
            query_id=query_id,
            line_number=line_number,
            status=EvaluationRecordStatus.INPUT_INVALID,
            error=EvaluationRecordError(code=code, message=message),
        )

    @classmethod
    def _build_assessment_inputs(
        cls, record: EvaluationInputRecord
    ) -> tuple[destiny_sdk.references.Reference, CandidateSelectionInput]:
        """Build the frozen scorer input and independently controlled query."""
        reference_id = uuid7()
        identifiers = [
            cls._parse_identifier(identifier) for identifier in record.input_identifiers
        ]
        authorship = cls._build_authorship(record.input_reference.authors)
        incoming = destiny_sdk.references.Reference(
            id=reference_id,
            identifiers=identifiers,
            enhancements=[
                destiny_sdk.enhancements.Enhancement(
                    reference_id=reference_id,
                    source=record.dataset_version,
                    visibility=destiny_sdk.visibility.Visibility.PUBLIC,
                    content=(
                        destiny_sdk.enhancements.BibliographicMetadataEnhancement(
                            title=record.input_reference.title,
                            authorship=authorship,
                            publication_year=record.input_reference.year,
                        )
                    ),
                )
            ],
        )
        query_identifiers = (
            [
                CandidateIdentifier.from_specific(identifier)
                for identifier in identifiers
            ]
            if "identifier" in record.route_applicability
            else []
        )
        selection_input = CandidateSelectionInput(
            title=record.input_reference.title,
            authors=record.input_reference.authors,
            publication_year=record.input_reference.year,
            identifiers=query_identifiers,
            excluded_reference_id=(
                record.excluded_reference_ids[0]
                if record.excluded_reference_ids
                else None
            ),
        )
        return incoming, selection_input

    @staticmethod
    def _parse_identifier(
        value: str,
    ) -> destiny_sdk.identifiers.ExternalIdentifier:
        """Parse one dataset identifier through the SDK's import identifier types."""
        lookup = destiny_sdk.identifiers.IdentifierLookup.parse(value)
        return destiny_sdk.identifiers.ExternalIdentifierAdapter.validate_python(
            lookup.model_dump()
        )

    @staticmethod
    def _build_authorship(
        authors: Sequence[str],
    ) -> list[destiny_sdk.enhancements.Authorship]:
        """Convert ordered display names to the SDK bibliographic shape."""
        last_index = len(authors) - 1
        return [
            destiny_sdk.enhancements.Authorship(
                display_name=display_name,
                position=(
                    destiny_sdk.enhancements.AuthorPosition.FIRST
                    if index == 0
                    else (
                        destiny_sdk.enhancements.AuthorPosition.LAST
                        if index == last_index
                        else destiny_sdk.enhancements.AuthorPosition.MIDDLE
                    )
                ),
            )
            for index, display_name in enumerate(authors)
        ]
