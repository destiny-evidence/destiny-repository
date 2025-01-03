from pydantic import BaseModel


class Example(BaseModel):
    id: str
    title: str
    description: str
    count: int
    tags: list[str]
