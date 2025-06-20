"""Generic types for inheritance of persistance classes."""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from app.persistence.es.persistence import GenericESPersistence

GenericESPersistenceType = TypeVar(
    "GenericESPersistenceType", bound="GenericESPersistence"
)
