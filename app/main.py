"""Main module for the DESTINY Climate and Health Repository API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import db_manager
from app.routers import imports

from .routers import example

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Lifespan hook for FastAPI."""
    db_manager.init(str(settings.db_url))
    yield
    await db_manager.close()


app = FastAPI(title="DESTINY Climate and Health Repository", lifespan=lifespan)

# This is an example router which can be removed when the project is more
# than just a skeleton.
app.include_router(example.router)
app.include_router(imports.router)


@app.get("/")
async def root() -> dict[str, str]:
    """
    Root endpoint for the API.

    Returns:
        dict[str, str]: A simple message.

    """
    return {"message": "Hello World"}
