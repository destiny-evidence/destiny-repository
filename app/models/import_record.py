"""Model describing import records."""

from enum import Enum, auto

from pydantic import BaseModel, PastDatetime


class ImportStatus(str, Enum):
    """Used to describe the status of an `Import`."""

    created = auto()
    started = auto()
    completed = auto()
    cancelled = auto()


class ImportRecord(BaseModel):
    """Model describing an import."""

    search_string: str
    searched_at: PastDatetime
    processor_name: str
    processor_version: str
    notes: str
    expected_record_count: int
    source_name: str
    status: ImportStatus = ImportStatus.created
