"""Repositories for imports and associated models."""

from abc import ABC

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import Enhancement as DomainEnhancement
from app.domain.references.models.models import (
    ExternalIdentifier as DomainExternalIdentifier,
)
from app.domain.references.models.models import Reference as DomainReference
from app.domain.references.models.sql import Enhancement as SQLEnhancement
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
