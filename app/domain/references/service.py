"""The service for interacting with and managing imports."""

import json

from pydantic import UUID4
from sqlalchemy.exc import IntegrityError

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
    ) -> ExternalIdentifierCreateResult:
        """Parse and ingest an external identifier into the database."""
        try:
            try:
                identifier = ExternalIdentifierCreate.model_validate(raw_identifier)
            except (TypeError, ValueError) as error:
                return ExternalIdentifierCreateResult(
                    error=f"""
Invalid identifier. Check the format and content of the identifier.
Attempted to parse:
{raw_identifier}
Error:
{error}
""",
                )

            db_identifier = ExternalIdentifier(
                reference_id=reference_id,
                **identifier.model_dump(),
            )

            try:
                created = await self.sql_uow.external_identifiers.add(db_identifier)
            except IntegrityError:
                return ExternalIdentifierCreateResult(
                    error=f"""
Identifier already exists on an existing reference.
Attempted to parse: {raw_identifier}
"""
                )
            return ExternalIdentifierCreateResult(identifier=created)

        except Exception as error:
            msg = f"Failed to create identifier from {raw_identifier}"
            logger.exception(msg)
            return ExternalIdentifierCreateResult(
                error=f"""
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
    ) -> EnhancementCreateResult:
        """Parse and ingest an enhancement into the database."""
        try:
            try:
                enhancement = EnhancementCreate.model_validate(raw_enhancement)
            except (TypeError, ValueError) as error:
                return EnhancementCreateResult(
                    error=f"""
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
Failed to create enhancement.
Error:
{error}
""",
            )

    async def ingest_reference(self, record_str: str) -> ReferenceCreateResult:
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
                    f"""
Could not parse reference: {record_str}.
Ensure the format is correct.
                """
                ]
            )

        reference = Reference(visibility=raw_reference.get("visibility"))

        # Check no keys other than enhancements and identifiers are present
        if surplus_keys := raw_reference.keys() - {"identifiers", "enhancements"}:
            return ReferenceCreateResult(
                errors=[
                    f"""
Unexpected keys found: {surplus_keys}.
Ensure the format is correct.
"""
                ]
            )

        if (
            not (raw_identifiers := raw_reference.get("identifiers"))
            or type(raw_identifiers) is not list
        ):
            return ReferenceCreateResult(
                errors=[
                    """
Could not parse identifiers.
Identifiers must be provided as a non-empty list. Ensure the format is correct."""
                ]
            )

        identifier_results: list[ExternalIdentifierCreateResult] = [
            await self.parse_and_ingest_external_identifier(
                reference.id,
                identifier,
            )
            for identifier in raw_identifiers
        ]

        # Fail out if all identifiers failed
        identifier_errors = [
            result.error for result in identifier_results if result.error
        ]
        if len(identifier_errors) == len(identifier_results):
            return ReferenceCreateResult(
                errors=["Could not parse any identifier.", *identifier_errors]
            )

        raw_enhancements = raw_reference.get("enhancements", [])
        if type(raw_enhancements) is not list:
            return ReferenceCreateResult(
                errors=[
                    *identifier_errors,
                    f"""
Could not parse enhancements: {raw_enhancements}.
Ensure the format is correct.
""",
                ]
            )

        # We have at least one identifier and the enhancements are either missing or
        # well-formed if we reach here, so we will proceed with the reference
        await self.sql_uow.references.add(reference)
        reference_result = ReferenceCreateResult(
            reference=Reference(),
            errors=[result.error for result in identifier_results if result.error],
        )

        enhancement_results: list[EnhancementCreateResult] = [
            await self.parse_and_ingest_enhancement(
                reference.id,
                enhancement,
            )
            for enhancement in raw_enhancements
        ]

        reference_result.errors.extend(
            [result.error for result in enhancement_results if result.error]
        )

        return reference_result
