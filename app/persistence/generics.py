"""Generic types for inheritance of persistance classes."""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from app.domain.base import SQLAttributeMixin
    from app.persistence.persistence import GenericPersistence

GenericPersistenceType = TypeVar("GenericPersistenceType", bound="GenericPersistence")
GenericDomainModelType = TypeVar("GenericDomainModelType", bound="SQLAttributeMixin")
