"""Main module for the DESTINY Climate and Health Repository API."""

from fastapi import FastAPI

from .routers import example

app = FastAPI(title="DESTINY Climate and Health Repository")

# This is an example router which can be removed when the project is more
# than just a skeleton.
app.include_router(example.router)


@app.get("/")
async def root() -> dict[str, str]:
    """
    Root endpoint for the API.

    Returns:
        dict[str, str]: A simple message.

    """
    return {"message": "Hello World"}
