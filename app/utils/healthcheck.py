"""Router for healthcheck endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.persistence.sql.session import get_session

router = APIRouter(prefix="/healthcheck", tags=["healthcheck"])
logger = get_logger()


@router.get("/", status_code=status.HTTP_200_OK)
async def get_healthcheck(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    """Verify we are able to connect to the database."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception as e:
        logger.exception("Database connection failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection failed.",
        ) from e

    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})
