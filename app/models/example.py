"""Example models for the API."""

from pydantic import BaseModel


class Example(BaseModel):
    """
    Demonstrate an example model for the API.

    Args:
        BaseModel (_type_): A Pydantic BaseModel object.

    """

    id: str
    title: str
    description: str
    count: int
    tags: list[str]
