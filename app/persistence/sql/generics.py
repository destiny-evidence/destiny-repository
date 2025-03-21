"""Generic types for inheritance of persistance classes."""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from sqlalchemy.orm import DeclarativeMeta

    from app.persistence.sql.dto import GenericSQLDTO

SQLDTOType = TypeVar("SQLDTOType", bound="GenericSQLDTO")
GenericSQLModelType = TypeVar("GenericSQLModelType", bound=type["DeclarativeMeta"])
