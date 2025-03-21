"""Generic types for inheritance of persistance classes."""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from app.domain.base import DomainBaseModel
    from app.persistence.dto import GenericDTO

DTOType = TypeVar("DTOType", bound="GenericDTO")
GenericDomainModelType = TypeVar("GenericDomainModelType", bound="DomainBaseModel")
