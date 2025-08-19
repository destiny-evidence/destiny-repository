"""Core classes for the Destiny SDK, not exposed to package users."""

from typing import Self

from pydantic import BaseModel

# These are non-standard newline characters that are not escaped by model_dump_json().
# We want jsonl files to have empirical new lines so they can be streamed line by line.
# Hence we replace each occurrence with standard new lines.
_ESCAPED_NEW_LINE = "\\n"
_UNSUPPORTED_NEWLINE_TRANSLATION = str.maketrans(
    {
        "\u0085": _ESCAPED_NEW_LINE,
        "\u2028": _ESCAPED_NEW_LINE,
        "\u2029": _ESCAPED_NEW_LINE,
    }
)


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
        return self.model_dump_json(exclude_none=True).translate(
            _UNSUPPORTED_NEWLINE_TRANSLATION
        )

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
