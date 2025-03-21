"""Generic types for inheritance of persistance classes."""

from typing import TypeVar

from sqlalchemy.ext.declarative import DeclarativeMeta

from app.persistence.sql.dto import GenericSQLDTO

SQLDTOType = TypeVar("SQLDTOType", bound=GenericSQLDTO)
GenericSQLModelType = TypeVar("GenericSQLModelType", bound=type[DeclarativeMeta])
