"""Router for handling management of imports."""

from fastapi import APIRouter, status

from app.models.import_record import ImportRecord

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_import(import_params: ImportRecord) -> ImportRecord:
    """Create a record for an import process."""
    return import_params
