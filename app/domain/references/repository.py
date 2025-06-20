"""Repositories for references and associated models."""

from abc import ABC
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import SQLNotFoundError
from app.domain.references.models.models import (
    BatchEnhancementRequest as DomainBatchEnhancementRequest,
)
from app.domain.references.models.models import Enhancement as DomainEnhancement
from app.domain.references.models.models import (
    EnhancementRequest as DomainEnhancementRequest,
)
from app.domain.references.models.models import (
    ExternalIdentifierType,
    GenericExternalIdentifier,
)
from app.domain.references.models.models import (
    LinkedExternalIdentifier as DomainExternalIdentifier,
)
from app.domain.references.models.models import Reference as DomainReference
from app.domain.references.models.sql import (
    BatchEnhancementRequest as SQLBatchEnhancementRequest,
)
from app.domain.references.models.sql import Enhancement as SQLEnhancement
from app.domain.references.models.sql import EnhancementRequest as SQLEnhancementRequest
from app.domain.references.models.sql import ExternalIdentifier as SQLExternalIdentifier
from app.domain.references.models.sql import Reference as SQLReference
from app.persistence.generics import GenericPersistenceType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.repository import GenericAsyncSqlRepository


class ReferenceRepositoryBase(
    GenericAsyncRepository[DomainReference, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for References."""


class ReferenceSQLRepository(
    GenericAsyncSqlRepository[DomainReference, SQLReference],
    ReferenceRepositoryBase,
):
    """Concrete implementation of a repository for references using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainReference,
            SQLReference,
        )

    async def get_hydrated(
        self,
        reference_ids: list[UUID],
        enhancement_types: list[str] | None = None,
        external_identifier_types: list[str] | None = None,
    ) -> list[DomainReference]:
        """Get a list of references with enhancements and identifiers by id."""
        query = select(SQLReference).where(SQLReference.id.in_(reference_ids))
        preload: list[str] = []
        if enhancement_types:
            query = query.options(
                joinedload(
                    SQLReference.enhancements.and_(
                        SQLEnhancement.enhancement_type.in_(enhancement_types)
                    )
                )
            )
            preload.append("enhancements")
        if external_identifier_types:
            query = query.options(
                joinedload(
                    SQLReference.identifiers.and_(
                        SQLExternalIdentifier.identifier_type.in_(
                            external_identifier_types
                        )
                    )
                )
            )
            preload.append("identifiers")
        result = await self._session.execute(query)
        db_references = result.unique().scalars().all()
        return [
            await db_reference.to_domain(preload=preload)
            for db_reference in db_references
        ]


class ExternalIdentifierRepositoryBase(
    GenericAsyncRepository[DomainExternalIdentifier, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for external identifiers."""


class ExternalIdentifierSQLRepository(
    GenericAsyncSqlRepository[DomainExternalIdentifier, SQLExternalIdentifier],
    ExternalIdentifierRepositoryBase,
):
    """Concrete implementation of a repository for identifiers using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainExternalIdentifier,
            SQLExternalIdentifier,
        )

    async def get_by_type_and_identifier(
        self,
        identifier_type: ExternalIdentifierType,
        identifier: str,
        other_identifier_name: str | None = None,
        preload: list[str] | None = None,
    ) -> DomainExternalIdentifier:
        """
        Get a single external identifier by type and identifier, if it exists.

        Args:
            identifier_type (ExternalIdentifierType): The type of the identifier.
            identifier (str): The identifier value.
            other_identifier_name (str | None): An optional name for another identifier.

        Returns:
            DomainExternalIdentifier | None: The external identifier if found.

        """
        query = select(SQLExternalIdentifier).where(
            SQLExternalIdentifier.identifier_type == identifier_type,
            SQLExternalIdentifier.identifier == identifier,
        )
        if other_identifier_name:
            query = query.where(
                SQLExternalIdentifier.other_identifier_name == other_identifier_name
            )
        if preload:
            for p in preload:
                relationship = getattr(SQLExternalIdentifier, p)
                query = query.options(joinedload(relationship))
        result = await self._session.execute(query)
        db_identifier = result.scalar_one_or_none()

        if not db_identifier:
            detail = (
                f"Unable to find {self._persistence_cls.__name__} with type "
                f"{identifier_type}, identifier {identifier}, and other "
                f"identifier name {other_identifier_name}"
            )
            raise SQLNotFoundError(
                detail=detail,
                lookup_model="ExternalIdentifier",
                lookup_type="external_identifier",
                lookup_value=(identifier_type, identifier, other_identifier_name),
            )

        return await db_identifier.to_domain(preload=preload)

    async def get_by_identifiers(
        self,
        identifiers: list[GenericExternalIdentifier],
    ) -> list[DomainExternalIdentifier]:
        """
        Get multiple external identifiers that match the given identifiers.

        :param identifiers: List of generic external identifiers to search for
        :type identifiers: list[GenericExternalIdentifier]
        :return: List of matching external identifiers found in the database
        :rtype: list[DomainExternalIdentifier]
        """
        if not identifiers:
            return []

        # Build OR conditions for each identifier combination
        conditions = []
        for identifier in identifiers:
            condition = (
                SQLExternalIdentifier.identifier_type == identifier.identifier_type
            ) & (SQLExternalIdentifier.identifier == identifier.identifier)
            if identifier.identifier_type == ExternalIdentifierType.OTHER:
                condition &= (
                    SQLExternalIdentifier.other_identifier_name
                    == identifier.other_identifier_name
                )
            conditions.append(condition)

        query = select(SQLExternalIdentifier).where(or_(*conditions))

        result = await self._session.execute(query)
        db_identifiers = result.unique().scalars().all()

        return [await db_identifier.to_domain() for db_identifier in db_identifiers]


class EnhancementRepositoryBase(
    GenericAsyncRepository[DomainEnhancement, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for external identifiers."""


class EnhancementSQLRepository(
    GenericAsyncSqlRepository[DomainEnhancement, SQLEnhancement],
    EnhancementRepositoryBase,
):
    """Concrete implementation of a repository for identifiers using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainEnhancement,
            SQLEnhancement,
        )


class EnhancementRequestRepositoryBase(
    GenericAsyncRepository[DomainEnhancementRequest, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for enhancement requests."""


class EnhancementRequestSQLRepository(
    GenericAsyncSqlRepository[DomainEnhancementRequest, SQLEnhancementRequest],
    EnhancementRequestRepositoryBase,
):
    """Concrete implementation of a repository for enhancement requests."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainEnhancementRequest,
            SQLEnhancementRequest,
        )


class BatchEnhancementRequestRepositoryBase(
    GenericAsyncRepository[DomainBatchEnhancementRequest, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for batch enhancement requests."""


class BatchEnhancementRequestSQLRepository(
    GenericAsyncSqlRepository[
        DomainBatchEnhancementRequest, SQLBatchEnhancementRequest
    ],
    BatchEnhancementRequestRepositoryBase,
):
    """Concrete implementation of a repository for batch enhancement requests."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainBatchEnhancementRequest,
            SQLBatchEnhancementRequest,
        )
