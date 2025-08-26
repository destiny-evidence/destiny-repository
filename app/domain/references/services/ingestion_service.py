"""Service for managing reference ingestion."""

import destiny_sdk

from app.core.exceptions import UnresolvableReferenceDuplicateError
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

        incoming_reference = (
            self._anti_corruption_service.reference_from_sdk_file_input(reference)
        )

        # To be replaced by duplicate detection logic!
        collided_identifiers = await self.fetch_collided_identifiers(
            [
                GenericExternalIdentifier.from_specific(identifier)
                for identifier in reference.identifiers
            ],
        )

        if not collided_identifiers:
            # No collision detected
            return incoming_reference

        if collision_strategy == CollisionStrategy.DISCARD:
            return None

        if collision_strategy == CollisionStrategy.FAIL:
            return f"""
Identifier(s) are already mapped on an existing reference:
{collided_identifiers}
"""

        # Perform merge
        existing_reference = await self.sql_uow.references.get_by_pk(
            collided_identifiers[0].reference_id,
            preload=["identifiers", "enhancements", "canonical_reference"],
        )

        try:
            delta_identifiers, delta_enhancements = existing_reference.merge(
                incoming_reference.identifiers or [],
                incoming_reference.enhancements or [],
                propagate=True,
            )
            logger.info(
                "Merging reference",
                collision_strategy=collision_strategy,
                existing_reference_id=str(existing_reference.id),
                incoming_reference_id=str(incoming_reference.id),
                n_delta_identifiers=len(delta_identifiers),
                n_delta_enhancements=len(delta_enhancements),
            )
        except UnresolvableReferenceDuplicateError as exc:
            logger.warning(
                "Merge could not be resolved.", error=exc.detail, exc_info=exc
            )
            return exc.detail

        if delta_identifiers or delta_enhancements:
            # This reference contained new information, store it as the
            # leaf of the canonical tree
            incoming_reference.duplicate_of = existing_reference.id
            incoming_reference.canonical_reference = existing_reference
            return incoming_reference

        # Nothing changed on the merge, incoming reference is discarded
        return None

    async def ingest_reference(
        self, record_str: str, entry_ref: int, collision_strategy: CollisionStrategy
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

        # We trace the first returned reference as it's always the canonical one
        # Looking at the log events or database state can show the full state
        trace_attribute(Attributes.REFERENCE_ID, str(collision_result.id))
        final_reference = await self.sql_uow.references.merge(collision_result)
        reference_create_result.reference_id = final_reference.id

        if reference_create_result.errors:
            reference_create_result.errors = [
                f"Entry {entry_ref}:",
                *reference_create_result.errors,
            ]

        return reference_create_result
