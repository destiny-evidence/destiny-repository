"""Run read-only deduplication assessments over supplied evaluation records."""

from collections.abc import Sequence
from enum import StrEnum, auto
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
    excluded_reference_ids: list[UUID] = Field(default_factory=list)
    dataset_version: str

    model_config = ConfigDict(extra="allow")


class EvaluationRecordResult(BaseModel):
    """Assessment or structured failure for one non-blank input line."""

    run_id: UUID
    query_id: str
    line_number: int
    status: EvaluationRecordStatus
    incoming_reference_id: UUID
    assessment: DeduplicationAssessment
    error: None = None


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
        record = EvaluationInputRecord.model_validate_json(line)
        incoming, selection_input = self._build_assessment_inputs(record)
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
