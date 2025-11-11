"""Models for search queries and results."""

from typing import Self

from pydantic import BaseModel, Field, PositiveInt, model_validator


class SearchResultTotal(BaseModel):
    """Information about the total number of search results."""

    count: int = Field(
        description="The total number of results matching the search criteria.",
    )
    is_lower_bound: bool = Field(
        description="Whether the count is a lower bound (true) or exact (false).",
    )


class SearchResultPage(BaseModel):
    """Information about the page of search results."""

    count: int = Field(
        description="The number of results on this page.",
    )
    number: int = Field(
        description="The page number of results returned, indexed from 1.",
    )


class PublicationYearRange(BaseModel):
    """A range of publication years for filtering search results."""

    start: PositiveInt | None = Field(
        None,
        description="Start year (inclusive)",
    )
    end: PositiveInt | None = Field(
        None,
        description="End year (inclusive)",
    )

    def serialize(self) -> str:
        """Serialize the publication year range to a string."""
        return f"[{self.start or "*"},{self.end or "*"}]"

    @model_validator(mode="after")
    def validate_end_ge_start(self) -> Self:
        """Validate that end year is greater than or equal to start year."""
        if self.start is not None and self.end is not None and self.end < self.start:
            msg = "End year must be greater than or equal to start year."
            raise ValueError(msg)
        return self
