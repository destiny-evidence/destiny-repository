"""
RIS citation-format model for reference exports.

RIS is the tagged interchange format consumed by reference managers (Zotero,
EndNote, Mendeley). Each record is a sequence of ``TAG  - value`` lines, begins
with the ``TY`` (reference type) tag and ends with ``ER``.
"""

import datetime
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.domain.base import ProjectedBaseModel
from app.utils.strings import demojibake, flatten_newlines


class RisType(StrEnum):
    """The subset of RIS reference-type codes this exporter emits."""

    JOURNAL = "JOUR"
    CONFERENCE = "CONF"
    SERIAL = "SER"
    BOOK = "BOOK"
    GENERIC = "GEN"


@dataclass(frozen=True)
class RisTag:
    """Associates a model field with its RIS tag (e.g. ``TI`` for the title)."""

    tag: str


class RisRecord(ProjectedBaseModel):
    """A single RIS record, projected from a reference and rendered by `render`."""

    reference_type: RisType = Field(description="RIS reference type (the `TY` tag).")
    title: Annotated[str | None, RisTag("TI")] = None
    authors: Annotated[list[str], RisTag("AU")] = Field(default_factory=list)
    publication_year: Annotated[int | None, RisTag("PY")] = None
    publication_date: Annotated[datetime.date | None, RisTag("DA")] = None
    journal: Annotated[str | None, RisTag("T2")] = None
    volume: Annotated[str | None, RisTag("VL")] = None
    issue: Annotated[str | None, RisTag("IS")] = None
    start_page: Annotated[str | None, RisTag("SP")] = None
    end_page: Annotated[str | None, RisTag("EP")] = None
    publisher: Annotated[str | None, RisTag("PB")] = None
    issns: Annotated[list[str], RisTag("SN")] = Field(default_factory=list)
    doi: Annotated[str | None, RisTag("DO")] = None
    accession: Annotated[str | None, RisTag("AN")] = None
    database: Annotated[str | None, RisTag("DB")] = None
    pdf_url: Annotated[str | None, RisTag("L1")] = None
    urls: Annotated[list[str], RisTag("UR")] = Field(default_factory=list)
    abstract: Annotated[str | None, RisTag("AB")] = None

    @classmethod
    def _field_tags(cls) -> dict[str, str]:
        """Map each tagged field to its RIS tag, in declaration (render) order."""
        return {
            name: meta.tag
            for name, field in cls.model_fields.items()
            for meta in field.metadata
            if isinstance(meta, RisTag)
        }

    def render(self, *, exclude: Collection[str] = frozenset({"abstract"})) -> str:
        r"""
        Render the record as an RIS string.

        The result is a single record (tag lines joined by ``\n``, terminated by
        the ``ER`` line) with no trailing newline; the caller joins records.
        """
        tags = self._field_tags()
        if unknown := set(exclude) - tags.keys():
            msg = f"Cannot exclude unknown RIS fields: {', '.join(sorted(unknown))}"
            raise ValueError(msg)
        lines = [self._line("TY", self.reference_type.value)]
        for name, tag in tags.items():
            if name in exclude:
                continue
            value = getattr(self, name)
            if isinstance(value, list):
                lines += [self._line(tag, item) for item in value if item]
            elif isinstance(value, datetime.date):
                lines.append(self._line(tag, value.strftime("%Y/%m/%d")))
            elif value is not None and value != "":
                lines.append(self._line(tag, value))
        lines.append("ER  - ")
        return "\n".join(lines)

    @staticmethod
    def _line(tag: str, value: object) -> str:
        """Format a single ``TAG  - value`` line, flattening internal newlines."""
        return f"{tag}  - {flatten_newlines(demojibake(str(value)))}"
