"""The service for interacting with and managing imports."""

from pydantic import UUID4

from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    Reference,
)
from app.persistence.sql.uow import AsyncSqlUnitOfWork


class ReferenceService:
    """The service which manages our imports and their processing."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        self.sql_uow = sql_uow

    async def get_reference(self, reference_id: UUID4) -> Reference | None:
        """Get a single import by id."""
        async with self.sql_uow:
            return await self.sql_uow.references.get_by_pk(
                reference_id, preload=["identifiers", "enhancements"]
            )

    async def register_reference(self) -> Reference:
        """Create a new reference."""
        async with self.sql_uow:
            created = await self.sql_uow.references.add(Reference())
            await self.sql_uow.commit()
            return created

    async def add_identifier(
        self, reference_id: UUID4, identifier: ExternalIdentifierCreate
    ) -> ExternalIdentifier:
        """Register an import, persisting it to the database."""
        async with self.sql_uow:
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

    async def add_enhancement(
        self, reference_id: UUID4, enhancement: EnhancementCreate
    ) -> Enhancement:
        """Register an import, persisting it to the database."""
        async with self.sql_uow:
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
