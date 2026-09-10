"""Models for search queries and results."""

from pydantic import BaseModel, Field


class SearchResultTotal(BaseModel):
    """Information about the total number of search results."""

    count: int = Field(
        description="The total number of results matching the search criteria, "
        "counted exactly rather than capped at the pageable window.",
    )
    is_lower_bound: bool = Field(
        default=False,
        deprecated=True,
        description="Whether the count is a lower bound. Totals are exact, so "
        "it is false.",
    )


class SearchResultPage(BaseModel):
    """Information about the page of search results."""

    count: int = Field(
        description="The number of results on this page.",
    )
    number: int = Field(
        description="The page number of results returned, indexed from 1.",
    )
    # Defaulted so a newer SDK can still parse a server that predates this field.
    max_result_window: int | None = Field(
        default=None,
        description="How many results pagination can reach.",
    )


class AnnotationFilter(BaseModel):
    """An annotation filter for search queries."""

    scheme: str = Field(
        description="The annotation scheme to filter by.",
        pattern=r"^[^/]+$",
    )
    label: str | None = Field(
        None,
        description="The annotation label to filter by.",
    )
    score: float | None = Field(
        None,
        description="The minimum score for the annotation filter.",
        ge=0.0,
        le=1.0,
    )

    def __repr__(self) -> str:
        """Serialize the annotation filter to a string."""
        annotation = self.scheme
        if self.label:
            annotation += f"/{self.label}"
        if self.score is not None:
            annotation += f"@{self.score}"
        return annotation

    def __str__(self) -> str:
        """Serialize the annotation filter to a string."""
        return repr(self)
