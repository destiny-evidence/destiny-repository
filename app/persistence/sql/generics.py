"""Generic types for inheritance of persistance classes."""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from app.persistence.sql.declarative_base import Base
    from app.persistence.sql.dto import GenericSQLDTO

SQLDTOType = TypeVar("SQLDTOType", bound="GenericSQLDTO")
GenericSQLModelType = TypeVar("GenericSQLModelType", bound="Base")
