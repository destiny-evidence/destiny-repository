"""The service for interacting with and managing imports."""

import json

from pydantic import UUID4

from app.core.logger import get_logger
from app.domain.imports.models.models import CollisionStrategy
from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    EnhancementParseResult,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    ExternalIdentifierParseResult,
    Reference,
    ReferenceCreate,
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
        return await self.sql_uow.references.add(Reference())

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
        self,
        raw_identifier: JSON,
        entry_ref: int,
    ) -> ExternalIdentifierParseResult:
        """Parse and ingest an external identifier into the database."""
        try:
            try:
                identifier = ExternalIdentifierCreate.model_validate(raw_identifier)
            except (TypeError, ValueError) as error:
                return ExternalIdentifierParseResult(
                    error=f"""
Identifier {entry_ref}:
    Invalid identifier. Check the format and content of the identifier.
    Attempted to parse:
    {raw_identifier}
    Error:
    {error}
""",
                )

            return ExternalIdentifierParseResult(external_identifier=identifier)

        except Exception as error:
            msg = f"Failed to create identifier from {raw_identifier}"
            logger.exception(msg)
            return ExternalIdentifierParseResult(
                error=f"""
Identifier {entry_ref}:
    Failed to create identifier.
    Attempted to parse:
    {raw_identifier}
    Error:
    {error}
""",
            )

    async def parse_enhancement(
        self,
        raw_enhancement: JSON,
        entry_ref: int,
    ) -> EnhancementParseResult:
        """Parse and ingest an enhancement into the database."""
        try:
            try:
                enhancement = EnhancementCreate.model_validate(raw_enhancement)
            except (TypeError, ValueError) as error:
                return EnhancementParseResult(
                    error=f"""
Enhancement {entry_ref}:
    Invalid enhancement. Check the format and content of the enhancement.
    Error:
    {error}
""",
                )
            return EnhancementParseResult(enhancement=enhancement)

        except Exception as error:
            msg = f"Failed to create enhancement from {raw_enhancement}"
            logger.exception(msg)
            return EnhancementParseResult(
                error=f"""
Enhancement {entry_ref}:
    Failed to create enhancement.
    Error:
    {error}
""",
            )

    async def detect_and_handle_collision(
        self,
        reference: ReferenceCreate,
        collision_strategy: CollisionStrategy,
    ) -> tuple[Reference | None, str | None]:
        """
        Detect and handle a collision with an existing reference.

        This is a placeholder for the actual collision handling logic.

        Args:
            incoming_reference: The incoming reference to check for collisions.
            collision_strategy: The strategy to use for handling collisions.

        Returns:
            A tuple containing the target state of the reference in the database
            (or None if no database operations are required), and an optional error
            message.

        """
        if not reference.identifiers:
            msg = "Cannot detect collision without identifiers."
            raise RuntimeError(msg)

        collided_identifiers = [
            _identifier
            for identifier in reference.identifiers
            if (
                _identifier
                := await self.sql_uow.external_identifiers.get_by_type_and_identifier(
                    identifier.identifier_type,
                    identifier.identifier,
                    identifier.other_identifier_name,
                )
            )
        ]

        if not collided_identifiers:
            # No collision, proceed with a new reference
            return Reference.from_create(reference), None

        if collision_strategy == CollisionStrategy.DISCARD:
            return None, None

        collided_references = {
            identifier.reference_id for identifier in collided_identifiers
        }

        if len(collided_references) != 1:
            return (
                None,
                """
            Incoming reference collides with more than one existing reference.
            """,
            )

        # If we get here, we have a single collision which we can now handle
        # First, we standardise the IDs
        existing_reference = await self.sql_uow.references.get_by_pk(
            collided_references.pop(), preload=["identifiers", "enhancements"]
        )
        if not existing_reference:
            msg = "Existing reference not found in database. This should not happen."
            raise RuntimeError(msg)
        incoming_reference = Reference.from_create(reference, existing_reference.id)

        if collision_strategy == CollisionStrategy.FAIL:
            return (
                None,
                f"""
    Identifier(s) are already mapped on an existing reference:
    {collided_identifiers}
    """,
            )
        if collision_strategy == CollisionStrategy.OVERWRITE:
            return incoming_reference, None

        # If we get here, we are merging
        target_reference_state, supplementary_reference_state = (
            (existing_reference, incoming_reference)
            if collision_strategy == CollisionStrategy.MERGE_DEFENSIVE
            else (incoming_reference, existing_reference)
        )

        if (
            not target_reference_state.identifiers
            or not supplementary_reference_state.identifiers
        ):
            msg = "No identifiers found in merge. This should not happen."
            raise RuntimeError(msg)

        target_reference_state.enhancements = target_reference_state.enhancements or []
        supplementary_reference_state.enhancements = (
            supplementary_reference_state.enhancements or []
        )

        # Merge the identifiers and enhancements
        target_reference_state.id = existing_reference.id
        target_reference_state.identifiers.extend(
            [
                identifier
                for identifier in supplementary_reference_state.identifiers
                if identifier.identifier_type
                not in {
                    identifier.identifier_type
                    for identifier in target_reference_state.identifiers
                }
            ]
        )
        target_reference_state.enhancements.extend(
            [
                enhancement
                for enhancement in supplementary_reference_state.enhancements
                if (enhancement.enhancement_type, enhancement.source)
                not in {
                    (enhancement.enhancement_type, enhancement.source)
                    for enhancement in target_reference_state.enhancements
                }
            ]
        )

        return target_reference_state, None

    async def validate_reference_format(
        self, raw_reference: JSON
    ) -> tuple[list[JSON], list[JSON], ReferenceCreateResult | None]:
        """Validate the format of the reference JSON."""
        if type(raw_reference) is not dict:
            return (
                [],
                [],
                ReferenceCreateResult(
                    errors=[
                        """
    Could not parse reference.
    Ensure the format is correct.
""",
                    ]
                ),
            )

        # Check no keys other than enhancements, identifiers and visibility are present
        if surplus_keys := raw_reference.keys() - {
            "identifiers",
            "enhancements",
            "visibility",
        }:
            return (
                [],
                [],
                ReferenceCreateResult(
                    errors=[
                        f"""
    Unexpected keys found: {surplus_keys}.
    Ensure the format is correct.
""",
                    ]
                ),
            )

        # Check the basic top-level structure
        if (
            not (raw_identifiers := raw_reference.get("identifiers"))
            or type(raw_identifiers) is not list
        ):
            return (
                [],
                [],
                ReferenceCreateResult(
                    errors=[
                        """
    Could not parse identifiers. Identifiers must be provided as a non-empty list.
    Ensure the format is correct.
""",
                    ]
                ),
            )

        raw_enhancements = raw_reference.get("enhancements", [])
        if type(raw_enhancements) is not list:
            return (
                [],
                [],
                ReferenceCreateResult(
                    errors=[
                        """
    Could not parse enhancements. Enhancements if providedmust be a list.
    Ensure the format is correct.
""",
                    ]
                ),
            )

        return raw_identifiers, raw_enhancements, None

    async def ingest_reference(
        self, record_str: str, entry_ref: int, collision_strategy: CollisionStrategy
    ) -> ReferenceCreateResult | None:
        """
        Attempt to ingest a reference into the database.

        This does an amount of manual format checking (instead of marshalling to the
        `ReferenceCreate` model) to provide more useful error messages to the user and
        allow for partial successes.
        """
        raw_reference: JSON = json.loads(record_str)

        raw_identifiers, raw_enhancements, error = await self.validate_reference_format(
            raw_reference
        )
        if error:
            return ReferenceCreateResult(errors=[f"Entry {entry_ref}:", *error.errors])

        identifier_results: list[ExternalIdentifierParseResult] = [
            await self.parse_external_identifier(identifier, i)
            for i, identifier in enumerate(raw_identifiers, 1)
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
            for i, enhancement in enumerate(raw_enhancements, 1)
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

        final_reference, collision_error = await self.detect_and_handle_collision(
            reference, collision_strategy
        )

        if collision_error:
            return ReferenceCreateResult(
                errors=[f"Entry {entry_ref}:", collision_error]
            )
        if not final_reference:
            # Record to be discarded
            return None

        await self.sql_uow.references.add(final_reference)

        reference_result = ReferenceCreateResult(
            reference=final_reference,
            errors=(
                [result.error for result in identifier_results if result.error]
                + [result.error for result in enhancement_results if result.error]
            ),
        )

        if reference_result.errors:
            reference_result.errors = [f"Entry {entry_ref}:", *reference_result.errors]

        return reference_result
