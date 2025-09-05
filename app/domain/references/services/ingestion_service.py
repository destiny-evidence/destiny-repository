"""Service for managing reference ingestion."""

import destiny_sdk

from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger
from app.domain.imports.models.models import CollisionStrategy
from app.domain.references.models.models import (
    GenericExternalIdentifier,
    LinkedExternalIdentifier,
    Reference,
)
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger(__name__)


class IngestionService(GenericService[ReferenceAntiCorruptionService]):
    """Service for managing reference ingestion."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow)

    async def fetch_collided_identifiers(
        self,
        identifiers: list[GenericExternalIdentifier],
    ) -> list[LinkedExternalIdentifier]:
        """
        Fetch identifiers that collide with existing identifiers in the database.

        Args:
            - identifiers (list[GenericExternalIdentifier]): The identifiers to check.

        Returns:
            - list[LinkedExternalIdentifier]: The collided identifiers.

        """
        return await self.sql_uow.external_identifiers.get_by_identifiers(identifiers)

    async def detect_and_handle_collision(
        self,
        reference: destiny_sdk.references.ReferenceFileInput,
        collision_strategy: CollisionStrategy,
    ) -> Reference | str | None:
        """
        Detect and handle a collision with an existing reference.

        Args:
            - reference (Reference): The incoming reference.
            - collision_strategy (CollisionStrategy): The strategy to use for
                handling collisions.

        Returns:
            - Reference | str | None: The final reference to be persisted, an
                error message, or None if the reference should be discarded.

        """
        if not reference.identifiers:
            msg = "No identifiers found in reference. This should not happen."
            raise RuntimeError(msg)

        collided_identifiers = await self.fetch_collided_identifiers(
            [
                GenericExternalIdentifier.from_specific(identifier)
                for identifier in reference.identifiers
            ],
        )

        if not collided_identifiers:
            # No collision detected
            return self._anti_corruption_service.reference_from_sdk_file_input(
                reference
            )

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

        incoming_reference = (
            self._anti_corruption_service.reference_from_sdk_file_input(
                reference, existing_reference.id
            )
        )

        # Merge collision strategies
        logger.info(
            "Merging reference",
            collision_strategy=collision_strategy,
            existing_reference_id=str(existing_reference.id),
        )
        await existing_reference.merge(incoming_reference, collision_strategy)
        return existing_reference

    async def validate_and_collide_reference(
        self,
        record_str: str,
        entry_ref: int,
        collision_strategy: CollisionStrategy,
    ) -> ReferenceCreateResult | None:
        """
        Attempt to ingest a reference into the database.

        This does an amount of manual format checking (instead of marshalling to the
        `ReferenceCreate` model) to provide more useful error messages to the user and
        allow for partial successes.
        """
        reference_create_result = await ReferenceCreateResult.from_raw(
            record_str, entry_ref
        )

        if not reference_create_result.reference:
            # Parsing failed, return the error
            return reference_create_result

        collision_result = await self.detect_and_handle_collision(
            reference_create_result.reference, collision_strategy
        )

        if collision_result is None:
            # Record to be discarded
            return None

        if isinstance(collision_result, str):
            logger.warning(
                "Reference collision could not be resolved",
                error=collision_result,
            )
            return ReferenceCreateResult(
                errors=[f"Entry {entry_ref}:", collision_result]
            )

        trace_attribute(Attributes.REFERENCE_ID, str(collision_result.id))
        reference_create_result.reference_id = collision_result.id

        if reference_create_result.errors:
            reference_create_result.errors = [
                f"Entry {entry_ref}:",
                *reference_create_result.errors,
            ]

        return reference_create_result
