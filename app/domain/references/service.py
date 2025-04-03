"""The service for interacting with and managing imports."""

from pydantic import UUID4

from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    Reference,
    ReferenceCreate,
)
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work


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

    async def ingest_record(self, record_str: str) -> Reference | None:
        """Attempt to ingest a reference into the database."""
        hydrated_reference = ReferenceCreate.model_validate_json(record_str)
        created = await self.sql_uow.references.add(Reference())
        for identifier in hydrated_reference.identifiers:
            db_identifier = ExternalIdentifier(
                reference_id=created.id,
                **identifier.model_dump(),
            )
            await self.sql_uow.external_identifiers.add(db_identifier)
        for enhancement in hydrated_reference.enhancements or []:
            db_enhancement = Enhancement(
                reference_id=created.id,
                **enhancement.model_dump(),
            )
            await self.sql_uow.enhancements.add(db_enhancement)
        return created
