"""Simple domain and persistence models for testing repositories."""

from typing import Literal, Self

import sqlalchemy as sa
from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import Integer, Text, mapped_field
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.persistence.es.index_manager import IndexManager
from app.persistence.es.persistence import GenericESPersistence
from app.persistence.sql.persistence import GenericSQLPersistence
from app.persistence.sql.repository import GenericAsyncSqlRepository


class SimpleDomainModel(DomainBaseModel, SQLAttributeMixin):
    """Simple domain document with basic fields."""

    title: str = "Test title"
    year: int = 2025
    content: str = "Sample content"


class SimpleSQLModel(GenericSQLPersistence[SimpleDomainModel]):
    """Simple SQL persistence model for testing."""

    __tablename__ = "simple_test_model"

    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Test title"
    )
    year: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=2025)
    content: Mapped[str] = mapped_column(
        String(1024), nullable=False, default="Sample content"
    )

    @classmethod
    def from_domain(cls, domain_obj: SimpleDomainModel) -> Self:
        """Create from domain model."""
        return cls(
            id=domain_obj.id,
            title=domain_obj.title,
            year=domain_obj.year,
            content=domain_obj.content,
        )

    def to_domain(self, preload: list | None = None) -> SimpleDomainModel:  # noqa: ARG002
        """Convert to domain model."""
        return SimpleDomainModel(
            id=self.id, title=self.title, year=self.year, content=self.content
        )


class SimpleSQLRepository(
    GenericAsyncSqlRepository[SimpleDomainModel, SimpleSQLModel, Literal["__none__"]]
):
    """Simple repository for testing base repository methods."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with just session, using default domain/persistence classes."""
        super().__init__(session, SimpleDomainModel, SimpleSQLModel)


class SimpleDoc(GenericESPersistence):
    """Simple test document with basic fields."""

    title: str = mapped_field(Text())
    year: int = mapped_field(Integer())
    content: str = mapped_field(Text())

    class Index:
        """Index metadata for the simple document."""

        name = "test_simple"

    def to_domain(self) -> SimpleDomainModel:
        """Convert to simple domain dict."""
        return SimpleDomainModel(
            id=self.meta.id,
            title=self.title,
            year=self.year,
            content=self.content,
        )

    @classmethod
    def from_domain(cls, domain_model: SimpleDomainModel) -> Self:
        """Create from simple domain dict."""
        return cls(
            meta={"id": domain_model.id},  # type: ignore[call-arg]
            title=domain_model.title,
            year=domain_model.year,
            content=domain_model.content,
        )


def simple_doc_index_manager(es_client: AsyncElasticsearch) -> IndexManager:
    """Create an index manager for the reference index."""
    return IndexManager(
        document_class=SimpleDoc,
        client=es_client,
    )
