"""Generic types for inheritance of persistance classes."""

from typing import TypeVar

from app.domain.base import DomainBaseModel
from app.persistence.dto import GenericDTO

DTOType = TypeVar("DTOType", bound=GenericDTO)
GenericDomainModelType = TypeVar("GenericDomainModelType", bound=DomainBaseModel)
