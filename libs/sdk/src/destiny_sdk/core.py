"""Core classes for the Destiny SDK, not exposed to package users."""

from typing import Self

from pydantic import BaseModel


class _JsonlFileInputMixIn(BaseModel):
    """
    A mixin class for models that are used at the top-level for entries in .jsonl files.

    This class is used to define a common interface for file input models.
    It is not intended to be used directly.
    """

    def to_jsonl(self) -> str:
        """
        Convert the model to a JSONL string.

        :return: The JSONL string representation of the model.
        :rtype: str
        """
        return self.model_dump_json(exclude_none=True)

    @classmethod
    def from_jsonl(cls, jsonl: str) -> Self:
        """
        Create an object from a JSONL string.

        :param jsonl: The JSONL string to parse.
        :type jsonl: str
        :return: The created object.
        :rtype: Self
        """
        return cls.model_validate_json(jsonl)
