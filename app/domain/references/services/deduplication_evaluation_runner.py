"""Run read-only deduplication assessments over supplied evaluation records."""

import json
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from enum import StrEnum, auto
from json import JSONDecodeError
from typing import Literal, Protocol
from uuid import UUID, uuid7

import destiny_sdk
from pydantic import BaseModel, ConfigDict, Field

from app.domain.references.models.models import (
    CandidateIdentifier,
    CandidateSelectionInput,
    DeduplicationAssessment,
    RetrievalPolicyName,
)


class EvaluationRecordStatus(StrEnum):
    """Result status for one non-blank evaluation input line."""

    ASSESSED = auto()
    INPUT_INVALID = auto()


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

    code: Literal["invalid_json", "invalid_record"]
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
        """Assess one supplied reference without writing repository state."""
        ...


class DeduplicationEvaluationRunner:
    """Convert supplied records and pass them to the read-only assessor."""

    def __init__(self, *, assessor: SuppliedReferenceAssessor) -> None:
        """Initialize the runner with its read-only assessment dependency."""
        self._assessor = assessor

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

        assessment = await self._assessor.evaluate_supplied(
            incoming,
            selection_input,
            retrieval_policy=retrieval_policy,
            k=k,
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
