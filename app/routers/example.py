"""Example router module."""

from fastapi import APIRouter, HTTPException

from app.models.example import Example

examples = [
    Example(
        id="foo",
        title="Example 1",
        description="This is the first example",
        count=1,
        tags=["tag1", "tag2"],
    ),
    Example(
        id="bar",
        title="Example 2",
        description="This is the second example",
        count=2,
        tags=["tag3", "tag4"],
    ),
    Example(
        id="bat",
        title="Example 3",
        description="This is the third example",
        count=3,
        tags=["tag5", "tag6"],
    ),
]

router = APIRouter(prefix="/examples", tags=["example"])


@router.get("/")
async def list_examples() -> list[Example]:
    """
    List all examples.

    Returns:
        list[Example]: _description_

    """
    return examples


@router.get("/{example_id}")
async def get_example(example_id: str) -> Example:
    """
    Retrieve a specific example.

    Args:
        example_id (str): An example ID.

    Raises:
        HTTPException: HTTP status code error if example is not found.

    Returns:
        Example: The example object.

    """
    for e in examples:
        if e.id == example_id:
            return e
    raise HTTPException(status_code=404, detail="Example not found")
