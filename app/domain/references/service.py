"""The service for interacting with and managing imports."""

import json

from pydantic import UUID4

from app.core.logger import get_logger
from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    EnhancementCreateResult,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    ExternalIdentifierCreateResult,
    Reference,
    ReferenceCreateResult,
)
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work
from app.utils.types import JSON

logger = get_logger()


class ReferenceService(GenericService):
    """The service which manages our imports and their processing."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)

    @unit_of_work
    async def get_reference(self, reference_id: UUID4) -> Reference | None:
        """Get a single import by id."""
        return await self.sql_uow.references.get_by_pk(
            reference_id, preload=["identifiers", "enhancements"]
        )

    @unit_of_work
    async def register_reference(self) -> Reference:
        """Create a new reference."""
        created = await self.sql_uow.references.add(Reference())
        await self.sql_uow.commit()
        return created

    @unit_of_work
    async def add_identifier(
        self, reference_id: UUID4, identifier: ExternalIdentifierCreate
    ) -> ExternalIdentifier:
        """Register an import, persisting it to the database."""
        reference = await self.sql_uow.references.get_by_pk(reference_id)
        if not reference:
            raise RuntimeError
        db_identifier = ExternalIdentifier(
            reference_id=reference.id,
            **identifier.model_dump(),
        )
        created = await self.sql_uow.external_identifiers.add(db_identifier)
        await self.sql_uow.commit()
        return created

    @unit_of_work
    async def add_enhancement(
        self, reference_id: UUID4, enhancement: EnhancementCreate
    ) -> Enhancement:
        """Register an import, persisting it to the database."""
        reference = await self.sql_uow.references.get_by_pk(reference_id)
        if not reference:
            raise RuntimeError
        db_enhancement = Enhancement(
            reference_id=reference.id,
            **enhancement.model_dump(),
        )
        created = await self.sql_uow.enhancements.add(db_enhancement)
        await self.sql_uow.commit()
        return created

    async def parse_and_ingest_external_identifier(
        self,
        reference_id: UUID4,
        raw_identifier: JSON,
        entry_ref: int,
    ) -> ExternalIdentifierCreateResult:
        """Parse and ingest an external identifier into the database."""
        try:
            try:
                identifier = ExternalIdentifierCreate.model_validate(raw_identifier)
            except (TypeError, ValueError) as error:
                return ExternalIdentifierCreateResult(
                    error=f"""
Identifier {entry_ref}:
    Invalid identifier. Check the format and content of the identifier.
    Attempted to parse:
    {raw_identifier}
    Error:
    {error}
""",
                )

            if await self.sql_uow.external_identifiers.get_by_type_and_identifier(
                identifier.identifier_type,
                identifier.identifier,
                identifier.other_identifier_name,
            ):
                return ExternalIdentifierCreateResult(
                    error=f"""
Identifier {entry_ref}:
    Identifier already exists on an existing reference.
    Attempted to parse:
    {raw_identifier}
"""
                )

            return ExternalIdentifierCreateResult(
                identifier=await self.sql_uow.external_identifiers.add(
                    ExternalIdentifier(
                        reference_id=reference_id,
                        **identifier.model_dump(),
                    )
                )
            )

        except Exception as error:
            msg = f"Failed to create identifier from {raw_identifier}"
            logger.exception(msg)
            return ExternalIdentifierCreateResult(
                error=f"""
Identifier {entry_ref}:
    Failed to create identifier.
    Attempted to parse:
    {raw_identifier}
    Error:
    {error}
""",
            )

    async def parse_and_ingest_enhancement(
        self,
        reference_id: UUID4,
        raw_enhancement: JSON,
        entry_ref: int,
    ) -> EnhancementCreateResult:
        """Parse and ingest an enhancement into the database."""
        try:
            try:
                enhancement = EnhancementCreate.model_validate(raw_enhancement)
            except (TypeError, ValueError) as error:
                return EnhancementCreateResult(
                    error=f"""
Enhancement {entry_ref}:
    Invalid enhancement. Check the format and content of the enhancement.
    Error:
    {error}
""",
                )
            db_enhancement = Enhancement(
                reference_id=reference_id,
                **enhancement.model_dump(),
            )
            created = await self.sql_uow.enhancements.add(db_enhancement)
            return EnhancementCreateResult(enhancement=created)

        except Exception as error:
            msg = f"Failed to create enhancement from {raw_enhancement}"
            logger.exception(msg)
            return EnhancementCreateResult(
                error=f"""
Enhancement {entry_ref}:
    Failed to create enhancement.
    Error:
    {error}
""",
            )

    async def ingest_reference(
        self, record_str: str, entry_ref: int
    ) -> ReferenceCreateResult:
        """
        Attempt to ingest a reference into the database.

        This does an amount of manual format checking (instead of marshalling to the
        `ReferenceCreate` model) to provide more useful error messages to the user and
        allow for partial successes.
        """
        raw_reference: JSON = json.loads(record_str)
        if type(raw_reference) is not dict:
            return ReferenceCreateResult(
                errors=[
                    f"Entry {entry_ref}:",
                    f"""
    Could not parse reference: {record_str}.
    Ensure the format is correct.
""",
                ]
            )

        reference = Reference(
            visibility=raw_reference.get(
                "visibility", Reference.model_fields["visibility"].get_default()
            )
        )

        # Check no keys other than enhancements, identifiers and visibility are present
        if surplus_keys := raw_reference.keys() - {
            "identifiers",
            "enhancements",
            "visibility",
        }:
            return ReferenceCreateResult(
                errors=[
                    f"Entry {entry_ref}:",
                    f"""
    Unexpected keys found: {surplus_keys}.
    Ensure the format is correct.
""",
                ]
            )

        # Check the basic top-level structure
        if (
            not (raw_identifiers := raw_reference.get("identifiers"))
            or type(raw_identifiers) is not list
        ):
            return ReferenceCreateResult(
                errors=[
                    f"Entry {entry_ref}:",
                    """
    Could not parse identifiers. Identifiers must be provided as a non-empty list.
    Ensure the format is correct.
""",
                ]
            )

        raw_enhancements = raw_reference.get("enhancements", [])
        if type(raw_enhancements) is not list:
            return ReferenceCreateResult(
                errors=[
                    f"Entry {entry_ref}:",
                    """
    Could not parse enhancements. Enhancements if providedmust be a list.
    Ensure the format is correct.
""",
                ]
            )

        # Create the reference in the database so the identifier FK can be set.
        # If no identifiers are created, we will remove it again.
        reference = await self.sql_uow.references.add(reference)

        identifier_results: list[ExternalIdentifierCreateResult] = [
            await self.parse_and_ingest_external_identifier(reference.id, identifier, i)
            for i, identifier in enumerate(raw_identifiers, 1)
        ]

        # Fail out if all identifiers failed
        identifier_errors = [
            result.error for result in identifier_results if result.error
        ]
        if len(identifier_errors) == len(identifier_results):
            await self.sql_uow.references.delete_by_pk(reference.id)
            return ReferenceCreateResult(
                errors=[
                    f"Entry {entry_ref:}",
                    "   All identifiers failed to parse.",
                    *identifier_errors,
                ]
            )

        reference_result = ReferenceCreateResult(
            reference=reference,
            errors=[
                *[result.error for result in identifier_results if result.error],
            ],
        )

        enhancement_results: list[EnhancementCreateResult] = [
            await self.parse_and_ingest_enhancement(reference.id, enhancement, i)
            for i, enhancement in enumerate(raw_enhancements, 1)
        ]

        reference_result.errors.extend(
            [result.error for result in enhancement_results if result.error]
        )

        if reference_result.errors:
            reference_result.errors = [f"Entry {entry_ref}:", *reference_result.errors]

        return reference_result
