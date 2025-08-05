"""
Pydantic models and adapters used to validate reference data.

A validator differs from an anti-corruption service in that it returns
information about the parsing process as well as the converted data.
"""

import json
from typing import Self

import destiny_sdk
from pydantic import UUID4, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from structlog import get_logger
from structlog.stdlib import BoundLogger

from app.domain.references.models.models import (
    ExternalIdentifier,
    ExternalIdentifierAdapter,
    Visibility,
)
from app.utils.types import JSON

logger: BoundLogger = get_logger(__name__)


class ReferenceFileInputValidator(BaseModel):
    """Validator for the top-level schema of a reference entry from a file."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list[JSON] = Field(min_length=1)
    enhancements: list[JSON] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ExternalIdentifierParseResult(BaseModel):
    """Result of an attempt to parse an external identifier."""

    external_identifier: ExternalIdentifier | None = Field(
        default=None,
        description="The external identifier to create",
        discriminator="identifier_type",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the parsing process",
    )

    @classmethod
    async def from_raw(cls, raw_identifier: JSON, entry_ref: int) -> Self:
        """Parse an external identifier from raw JSON."""
        try:
            identifier: ExternalIdentifier = ExternalIdentifierAdapter.validate_python(
                raw_identifier
            )
            return cls(external_identifier=identifier)
        except (TypeError, ValueError) as error:
            return cls(
                error=f"""
Identifier {entry_ref}:
Invalid identifier. Check the format and content of the identifier.
Attempted to parse:
{raw_identifier}
Error:
{error}
"""
            )
        except Exception as error:
            logger.exception(
                "Failed to create identifier",
                raw_identifier=raw_identifier,
                entry_ref=entry_ref,
            )
            return cls(
                error=f"""
Identifier {entry_ref}:
Failed to create identifier.
Attempted to parse:
{raw_identifier}
Error:
{error}
"""
            )


class EnhancementParseResult(BaseModel):
    """Result of an attempt to parse an enhancement."""

    enhancement: destiny_sdk.enhancements.EnhancementFileInput | None = Field(
        default=None,
        description="The enhancement to create",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the parsing process",
    )

    @classmethod
    async def from_raw(cls, raw_enhancement: JSON, entry_ref: int) -> Self:
        """Parse an enhancement from raw JSON."""
        try:
            enhancement = destiny_sdk.enhancements.EnhancementFileInput.model_validate(
                raw_enhancement
            )
            return cls(enhancement=enhancement)
        except (TypeError, ValueError) as error:
            return cls(
                error=f"""
Enhancement {entry_ref}:
Invalid enhancement. Check the format and content of the enhancement.
Error:
{error}
"""
            )
        except Exception as error:
            logger.exception(
                "Failed to create enhancement",
                raw_enhancement=raw_enhancement,
                entry_ref=entry_ref,
            )
            return cls(
                error=f"""
Enhancement {entry_ref}:
Failed to create enhancement.
Error:
{error}
"""
            )


class ReferenceCreateResult(BaseModel):
    """
    Result of an attempt to create a reference.

    If reference is None, no reference was created and errors will be populated.
    If reference exists and there are errors, the reference was created but there
    were errors in the hydration.
    If reference exists and there are no errors, the reference was created and all
    enhancements/identifiers were hydrated successfully from the input.
    """

    reference: destiny_sdk.references.ReferenceFileInput | None = Field(
        default=None,
        description="""
    The created reference.
    If None, no reference was created.
    """,
    )
    errors: list[str] = Field(
        default_factory=list,
        description="A list of errors encountered during the creation process",
    )
    reference_id: UUID4 | None = Field(
        default=None,
        description="The ID of the created reference, if created",
    )

    @property
    def error_str(self) -> str | None:
        """Return a string of errors if they exist."""
        return "\n\n".join(e.strip() for e in self.errors) if self.errors else None

    @classmethod
    async def from_raw(
        cls,
        record_str: str,
        entry_ref: int,
    ) -> Self:
        """Parse a reference file input from a string and validate it."""
        try:
            raw_reference: dict = json.loads(record_str)
            # Validate top-level JSON schema using Pydantic
            validated_input = ReferenceFileInputValidator.model_validate(raw_reference)
        except (json.JSONDecodeError, ValidationError) as exc:
            return cls(errors=[f"Entry {entry_ref}:", str(exc)])

        identifier_results: list[ExternalIdentifierParseResult] = [
            await ExternalIdentifierParseResult.from_raw(identifier, entry_ref)
            for entry_ref, identifier in enumerate(validated_input.identifiers, 1)
        ]

        # Fail out if all identifiers failed
        identifier_errors = [
            result.error for result in identifier_results if result.error
        ]
        if len(identifier_errors) == len(identifier_results):
            return cls(
                errors=[
                    f"Entry {entry_ref:}",
                    "   All identifiers failed to parse.",
                    *identifier_errors,
                ]
            )

        enhancement_results: list[EnhancementParseResult] = [
            await EnhancementParseResult.from_raw(enhancement, entry_ref)
            for entry_ref, enhancement in enumerate(validated_input.enhancements, 1)
        ]

        return cls(
            reference=destiny_sdk.references.ReferenceFileInput(
                visibility=raw_reference.get(  # type: ignore[union-attr]
                    "visibility",
                    destiny_sdk.references.ReferenceFileInput.model_fields[
                        "visibility"
                    ].get_default(),
                ),
                identifiers=[
                    result.external_identifier
                    for result in identifier_results
                    if result.external_identifier
                ],
                enhancements=[
                    result.enhancement
                    for result in enhancement_results
                    if result.enhancement
                ],
            ),
            errors=[result.error for result in identifier_results if result.error]
            + [result.error for result in enhancement_results if result.error],
        )


class BatchEnhancementResultValidator(BaseModel):
    """Result of a batch enhancement request."""

    enhancement_to_add: destiny_sdk.enhancements.Enhancement | None = Field(
        default=None,
        description="An enhancement to add to the references",
    )
    robot_error: destiny_sdk.robots.LinkedRobotError | None = Field(
        default=None,
        description="An error encountered by the robot during processing",
    )
    parse_failure: str | None = Field(
        default=None,
        description=("An error encountered while parsing the batch enhancement result"),
    )

    @classmethod
    async def from_raw(
        cls, entry: str, entry_ref: int, expected_reference_ids: set[UUID4]
    ) -> Self:
        """Create a BatchEnhancementResult from a jsonl entry."""
        file_entry_validator: TypeAdapter[
            destiny_sdk.robots.BatchEnhancementResultEntry
        ] = TypeAdapter(destiny_sdk.robots.BatchEnhancementResultEntry)

        try:
            file_entry = file_entry_validator.validate_json(entry)
        except ValidationError as exception:
            return cls(
                parse_failure=f"Entry {entry_ref} could not be parsed: {exception}."
            )

        if file_entry.reference_id not in expected_reference_ids:
            return cls(
                robot_error=destiny_sdk.robots.LinkedRobotError(
                    reference_id=file_entry.reference_id,
                    message="Reference not in batch enhancement request.",
                )
            )

        if isinstance(file_entry, destiny_sdk.enhancements.Enhancement):
            return cls(
                enhancement_to_add=file_entry,
            )
        return cls(robot_error=file_entry)
