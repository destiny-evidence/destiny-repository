"""The service for interacting with and managing imports."""

import json
import uuid

from pydantic import UUID4, ValidationError

from app.core.logger import get_logger
from app.domain.imports.models.models import CollisionStrategy
from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    EnhancementParseResult,
    EnhancementRequest,
    EnhancementType,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    ExternalIdentifierParseResult,
    ExternalIdentifierSearch,
    Reference,
    ReferenceCreate,
    ReferenceCreateInputValidator,
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
        """Get a single reference by id."""
        return await self.sql_uow.references.get_by_pk(
            reference_id, preload=["identifiers", "enhancements"]
        )

    @unit_of_work
    async def get_reference_from_identifier(
        self, identifier: ExternalIdentifierSearch
    ) -> Reference | None:
        """Get a single reference by identifier."""
        db_identifier = (
            await self.sql_uow.external_identifiers.get_by_type_and_identifier(
                identifier.identifier_type,
                identifier.identifier,
                identifier.other_identifier_name,
            )
        )
        if not db_identifier:
            return None
        return await self.sql_uow.references.get_by_pk(
            db_identifier.reference_id, preload=["identifiers", "enhancements"]
        )

    @unit_of_work
    async def register_reference(self) -> Reference:
        """Create a new reference."""
        return await self.sql_uow.references.add(Reference())

    @unit_of_work
    async def register_enhancement_request(
        self, reference_id: UUID4, enhancement_type: EnhancementType
    ) -> EnhancementRequest:
        """Create an enhancement request."""
        enhancement_request = EnhancementRequest(
            request_id=uuid.uuid4(),
            reference_id=reference_id,
            enhancement_type=enhancement_type,
        )

        return await self.sql_uow.enhancement_requests.add(enhancement_request)

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
        return await self.sql_uow.external_identifiers.add(db_identifier)

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
        return await self.sql_uow.enhancements.add(db_enhancement)

    async def parse_external_identifier(
        self, raw_identifier: JSON, entry_ref: int
    ) -> ExternalIdentifierParseResult:
        """Parse and ingest an external identifier into the database."""
        try:
            identifier = ExternalIdentifierCreate.model_validate(raw_identifier)
            return ExternalIdentifierParseResult(external_identifier=identifier)
        except (TypeError, ValueError) as error:
            return ExternalIdentifierParseResult(
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
                "Failed to create identifier", extra={"raw_identifier": raw_identifier}
            )
            return ExternalIdentifierParseResult(
                error=f"""
Identifier {entry_ref}:
    Failed to create identifier.
    Attempted to parse:
    {raw_identifier}
    Error:
    {error}
    """
            )

    async def parse_enhancement(
        self, raw_enhancement: JSON, entry_ref: int
    ) -> EnhancementParseResult:
        """Parse and ingest an enhancement into the database."""
        try:
            enhancement = EnhancementCreate.model_validate(raw_enhancement)
            return EnhancementParseResult(enhancement=enhancement)
        except (TypeError, ValueError) as error:
            return EnhancementParseResult(
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
                extra={"raw_enhancement": raw_enhancement},
            )
            return EnhancementParseResult(
                error=f"""
Enhancement {entry_ref}:
    Failed to create enhancement.
    Error:
    {error}
    """
            )

    async def detect_and_handle_collision(
        self,
        reference: ReferenceCreate,
        collision_strategy: CollisionStrategy,
    ) -> Reference | str | None:
        """
        Detect and handle a collision with an existing reference.

        Args:
            - reference (ReferenceCreate): The incoming reference.
            - collision_strategy (CollisionStrategy): The strategy to use for
                handling collisions.

        Returns:
            - Reference | str | None: The final reference to be persisted, an
                error message, or None if the reference should be discarded.

        """
        if not reference.identifiers:
            msg = "No identifiers found in reference. This should not happen."
            raise RuntimeError(msg)

        collided_identifiers = await self._fetch_collided_identifiers(
            reference.identifiers
        )

        if not collided_identifiers:
            # No collision detected
            return Reference.from_create(reference)

        if collision_strategy == CollisionStrategy.DISCARD:
            return None

        collided_refs = {identifier.reference_id for identifier in collided_identifiers}
        if len(collided_refs) != 1:
            return "Incoming reference collides with more than one existing reference."

        if collision_strategy == CollisionStrategy.FAIL:
            return f"""
Identifier(s) are already mapped on an existing reference:
{collided_identifiers}
"""

        existing_reference = await self.sql_uow.references.get_by_pk(
            collided_refs.pop(), preload=["identifiers", "enhancements"]
        )
        if not existing_reference:
            msg = "Existing reference not found in database. This should not happen."
            raise RuntimeError(msg)

        incoming_reference = Reference.from_create(reference, existing_reference.id)

        # Merge collision strategies
        logger.info(
            "Merging reference",
            extra={
                "collision_strategy": collision_strategy,
                "reference_id": existing_reference.id,
            },
        )
        return await self._merge_references(
            incoming_reference, existing_reference, collision_strategy
        )

    async def _fetch_collided_identifiers(
        self, identifiers: list[ExternalIdentifierCreate]
    ) -> list[ExternalIdentifier]:
        """
        Fetch identifiers that collide with existing identifiers in the database.

        Args:
            - identifiers (list[ExternalIdentifierCreate]): The identifiers to check.

        Returns:
            - list[ExternalIdentifier]: The collided identifiers.

        """
        collided = []
        for identifier in identifiers:
            existing_identifier = (
                await self.sql_uow.external_identifiers.get_by_type_and_identifier(
                    identifier.identifier_type,
                    identifier.identifier,
                    identifier.other_identifier_name,
                )
            )
            if existing_identifier:
                collided.append(existing_identifier)
        return collided

    async def _merge_references(
        self,
        incoming_reference: Reference,
        existing_reference: Reference,
        collision_strategy: CollisionStrategy,
    ) -> Reference:
        """
        Merge two references together.

        Args:
            - existing_reference (Reference): The existing reference.
            - incoming_reference (Reference): The incoming reference.
            - collision_strategy (CollisionStrategy): The strategy to use for
                handling collisions.

        Returns:
            - Reference: The final reference to be persisted.

        """
        # Graft matching IDs from existing to incoming
        # This allows SQLAlchemy to handle the merge correctly
        for identifier in incoming_reference.identifiers or []:
            for existing_identifier in existing_reference.identifiers or []:
                if (identifier.identifier_type, identifier.other_identifier_name) == (
                    existing_identifier.identifier_type,
                    existing_identifier.other_identifier_name,
                ):
                    identifier.id = existing_identifier.id
        for enhancement in incoming_reference.enhancements or []:
            for existing_enhancement in existing_reference.enhancements or []:
                if (enhancement.enhancement_type, enhancement.source) == (
                    existing_enhancement.enhancement_type,
                    existing_enhancement.source,
                ):
                    enhancement.id = existing_enhancement.id

        # Decide merge order based on strategy
        target, supplementary = (
            (existing_reference, incoming_reference)
            if collision_strategy == CollisionStrategy.MERGE_DEFENSIVE
            else (incoming_reference, existing_reference)
        )

        if not target.identifiers or not supplementary.identifiers:
            msg = "No identifiers found in merge. This should not happen."
            raise RuntimeError(msg)

        target.enhancements = target.enhancements or []
        supplementary.enhancements = supplementary.enhancements or []

        # Merge identifiers and enhancements
        target.identifiers.extend(
            [
                identifier
                for identifier in supplementary.identifiers
                if (identifier.identifier_type, identifier.other_identifier_name)
                not in {
                    (identifier.identifier_type, identifier.other_identifier_name)
                    for identifier in target.identifiers
                }
            ]
        )

        # On an overwrite, we don't preserve the existing enhancements, only identifiers
        if collision_strategy == CollisionStrategy.OVERWRITE:
            return target

        target.enhancements.extend(
            [
                enhancement
                for enhancement in supplementary.enhancements
                if (enhancement.enhancement_type, enhancement.source)
                not in {
                    (enhancement.enhancement_type, enhancement.source)
                    for enhancement in target.enhancements
                }
            ]
        )

        return target

    async def ingest_reference(
        self, record_str: str, entry_ref: int, collision_strategy: CollisionStrategy
    ) -> ReferenceCreateResult | None:
        """
        Attempt to ingest a reference into the database.

        This does an amount of manual format checking (instead of marshalling to the
        `ReferenceCreate` model) to provide more useful error messages to the user and
        allow for partial successes.
        """
        try:
            raw_reference: dict = json.loads(record_str)
            # Validate top-level JSON schema using Pydantic
            validated_input = ReferenceCreateInputValidator.model_validate(
                raw_reference
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            return ReferenceCreateResult(errors=[f"Entry {entry_ref}:", str(exc)])

        identifier_results: list[ExternalIdentifierParseResult] = [
            await self.parse_external_identifier(identifier, i)
            for i, identifier in enumerate(validated_input.identifiers, 1)
        ]

        # Fail out if all identifiers failed
        identifier_errors = [
            result.error for result in identifier_results if result.error
        ]
        if len(identifier_errors) == len(identifier_results):
            return ReferenceCreateResult(
                errors=[
                    f"Entry {entry_ref:}",
                    "   All identifiers failed to parse.",
                    *identifier_errors,
                ]
            )

        enhancement_results: list[EnhancementParseResult] = [
            await self.parse_enhancement(enhancement, i)
            for i, enhancement in enumerate(validated_input.enhancements, 1)
        ]

        reference = ReferenceCreate(
            visibility=raw_reference.get(  # type: ignore[union-attr]
                "visibility", Reference.model_fields["visibility"].get_default()
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
        )

        collision_result = await self.detect_and_handle_collision(
            reference, collision_strategy
        )

        if collision_result is None:
            # Record to be discarded
            return None

        if isinstance(collision_result, str):
            logger.info(
                "Reference collision could not be resolved",
                extra={"error": collision_result},
            )
            return ReferenceCreateResult(
                errors=[f"Entry {entry_ref}:", collision_result]
            )

        final_reference = await self.sql_uow.references.merge(collision_result)

        reference_result = ReferenceCreateResult(
            reference=final_reference,
            errors=(
                [result.error for result in identifier_results if result.error]
                + [result.error for result in enhancement_results if result.error]
            ),
        )

        logger.info(
            "Reference ingested",
            extra={
                "reference_id": final_reference.id,
                "n_identifiers": len(final_reference.identifiers or []),
                "n_enhancements": len(final_reference.enhancements or []),
                "n_errors": len(reference_result.errors),
            },
        )

        if reference_result.errors:
            reference_result.errors = [f"Entry {entry_ref}:", *reference_result.errors]

        return reference_result
