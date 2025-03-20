"""Generic repositories define expected functionality."""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import UUID4
from sqlmodel import SQLModel

T = TypeVar("T", bound=SQLModel)


class GenericAsyncRepository(Generic[T], ABC):
    """The core interface expected of a repository implementation."""

    @abstractmethod
    async def get_by_pk(self, pk: UUID4, preload: list[str] | None = None) -> T | None:
        """
        Get a record using its primary key.

        Args:
        - pk (UUID4): The primary key to use to look up the record.
        - preload (list[str]): A list of attributes to preload using a join.

        """
        raise NotImplementedError

    @abstractmethod
    async def add(self, record: T) -> T:
        """
        Add a record to the repository.

        Args:
        - record (T): The record to be persisted.

        Note:
        While a record may have been added to a repository, its persistence
        relies on the underlying storage, which may use transactions which will
        need to be committed either in the concrete implementation of this method
        or external to the repository.

        """
        raise NotImplementedError
