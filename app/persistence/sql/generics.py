"""Generic types for inheritance of persistance classes."""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from app.persistence.sql.persistence import GenericSQLPersistence

GenericSQLPersistenceType = TypeVar(
    "GenericSQLPersistenceType", bound="GenericSQLPersistence"
)
GenericSQLPreloadableType = TypeVar("GenericSQLPreloadableType", bound=str)
