"""Parser for a EPPI JSON export file."""

import base64
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from destiny_sdk.core import UUID
from destiny_sdk.enhancements import (
    AbstractContentEnhancement,
    AbstractProcessType,
    AnnotationEnhancement,
    AnnotationType,
    AuthorPosition,
    Authorship,
    BibliographicMetadataEnhancement,
    BooleanAnnotation,
    Enhancement,
    EnhancementContent,
    EnhancementFileInput,
    RawEnhancement,
)
from destiny_sdk.identifiers import (
    DOIIdentifier,
    ERICIdentifier,
    ExternalIdentifier,
    OpenAlexIdentifier,
    OtherIdentifier,
    ProQuestIdentifier,
)
from destiny_sdk.parsers.exceptions import (
    ExternalIdentifierNotFoundError,
    ReferenceIdNotFoundError,
)
from destiny_sdk.references import ReferenceFileInput
from destiny_sdk.visibility import Visibility

# The URL field of an EPPI export may hold a link to the reference in destiny, e.g.
# https://data.evidence-repository.org/esea/references/019f880e-2c39-7138-a387-221808f02d98
REFERENCE_URL_PATTERN = re.compile(r"/references/(?P<reference_id>[0-9a-fA-F-]{36})/?$")

_REFERENCE_ID_ADAPTER: TypeAdapter[UUID] = TypeAdapter(UUID)


def load_eppi_export(export_path: Path, codec: str = "utf-8") -> tuple[dict, str]:
    """
    Load an EPPI export, returning its data and a checksum of the file.

    Args:
        export_path (Path): The EPPI export file to load.
        codec (str): The codec to decode the file with.

    Returns:
        tuple[dict, str]: The parsed export and the base64 md5 checksum of the file.

    """
    file_bytes = export_path.read_bytes()
    checksum = base64.b64encode(hashlib.md5(file_bytes).digest()).decode("ascii")  # noqa: S324

    # errors='replace' is deliberate: EPPI exports occasionally contain CESU-8
    # surrogate pairs for non-BMP chars (e.g. mathematical italics) that strict
    # UTF-8 rejects. We'd rather degrade those rare chars to U+FFFD than fail
    # the whole import.
    return json.loads(file_bytes.decode(codec, errors="replace")), checksum


class EPPIParser:
    """
    Parser for an EPPI JSON export file.

    See example here: https://eppi.ioe.ac.uk/cms/Portals/35/Maps/Examples/example_orignal.json
    """

    version = "2.0"

    def __init__(  # noqa: PLR0913
        self,
        *,
        tags: list[str] | None = None,
        include_raw_data: bool = False,
        include_eppi_id: bool = False,
        source_export_date: datetime | None = None,
        data_description: str | None = None,
        raw_enhancement_excludes: list[str] | None = None,
    ) -> None:
        """
        Initialize the EPPIParser with optional tags.

        Args:
            tags (list[str] | None): Optional list of tags to annotate references.
            include_eppi_id (bool): Whether to include the EPPI ItemId as an
                OtherIdentifier on each reference.

        """
        self.tags = tags or []
        self.parser_source = f"destiny_sdk.eppi_parser@{self.version}"
        self.include_raw_data = include_raw_data
        self.include_eppi_id = include_eppi_id
        self.source_export_date = source_export_date
        self.data_description = data_description
        self.raw_enhancement_excludes = (
            raw_enhancement_excludes if raw_enhancement_excludes else []
        )

        if self.include_raw_data and not all(
            (
                self.source_export_date,
                self.data_description,
            )
        ):
            msg = (
                "Cannot include raw data enhancements without "
                "source_export_date, data_description, and raw_enhancement_metadata"
            )
            raise RuntimeError(msg)

    def _parse_identifiers(
        self, ref_to_import: dict[str, Any]
    ) -> list[ExternalIdentifier]:
        identifiers: list[ExternalIdentifier] = []
        if self.include_eppi_id and (item_id := ref_to_import.get("ItemId")):
            identifiers.append(
                OtherIdentifier(
                    identifier=str(item_id),
                    other_identifier_name="EPPI ItemId",
                )
            )

        if doi := ref_to_import.get("DOI"):
            doi_identifier = self._parse_doi(doi=doi)
            if doi_identifier:
                identifiers.append(doi_identifier)

        if url := ref_to_import.get("URL"):
            identifier = self._parse_url_to_identifier(url=url)
            if identifier and identifier not in identifiers:
                identifiers.append(identifier)

        if not identifiers:
            msg = (
                "No known external identifiers found for Reference data "
                f"with DOI: '{doi if doi else None}' "
                f"and URL: '{url if url else None}'."
            )
            raise ExternalIdentifierNotFoundError(detail=msg)

        return identifiers

    def _parse_reference_id(self, ref_to_import: dict[str, Any]) -> UUID | None:
        """Attempt to parse a destiny reference id from the URL field."""
        url = (ref_to_import.get("URL") or "").strip()
        match = REFERENCE_URL_PATTERN.search(url)
        if not match:
            return None

        try:
            return _REFERENCE_ID_ADAPTER.validate_python(match.group("reference_id"))
        except ValidationError:
            return None

    def _parse_doi(self, doi: str) -> DOIIdentifier | None:
        """Attempt to parse a DOI from a string."""
        try:
            doi = doi.strip()
            return DOIIdentifier(identifier=doi)
        except ValidationError:
            return None

    def _parse_url_to_identifier(self, url: str) -> ExternalIdentifier | None:
        """Attempt to parse an external identifier from a url string."""
        url = url.strip()
        identifier_cls: type[ExternalIdentifier] | None = None
        if "doi.org" in url:
            identifier_cls = DOIIdentifier
        elif "eric" in url:
            identifier_cls = ERICIdentifier
        elif "proquest" in url:
            identifier_cls = ProQuestIdentifier
        elif "openalex" in url:
            identifier_cls = OpenAlexIdentifier
        else:
            return None

        try:
            return identifier_cls(identifier=url)
        except ValidationError:
            return None

    def _parse_abstract_enhancement(
        self, ref_to_import: dict[str, Any]
    ) -> EnhancementContent | None:
        if abstract := ref_to_import.get("Abstract"):
            return AbstractContentEnhancement(
                process=AbstractProcessType.OTHER,
                abstract=abstract,
            )
        return None

    def _parse_bibliographic_enhancement(
        self, ref_to_import: dict[str, Any]
    ) -> EnhancementContent | None:
        title = ref_to_import.get("Title")
        publication_year = (
            int(year)
            if (year := ref_to_import.get("Year")) and year.isdigit()
            else None
        )
        publisher = ref_to_import.get("Publisher")
        authors_string = ref_to_import.get("Authors")

        authorships = []
        if authors_string:
            authors = [
                author.strip() for author in authors_string.split(";") if author.strip()
            ]
            for i, author_name in enumerate(authors):
                position = AuthorPosition.MIDDLE
                if i == 0:
                    position = AuthorPosition.FIRST
                if i == len(authors) - 1 and i > 0:
                    position = AuthorPosition.LAST

                authorships.append(
                    Authorship(
                        display_name=author_name,
                        position=position,
                    )
                )

        if not title and not publication_year and not publisher and not authorships:
            return None

        return BibliographicMetadataEnhancement(
            title=title,
            publication_year=publication_year,
            publisher=publisher,
            authorship=authorships if authorships else None,
        )

    def _raw_enhancement_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        """Identify the codesets the codes in an export belong to."""
        return {
            "codeset_ids": [
                codeset.get("SetId") for codeset in data.get("CodeSets", [])
            ]
        }

    def _parse_raw_enhancement(
        self, ref_to_import: dict[str, Any], raw_enhancement_metadata: dict[str, Any]
    ) -> RawEnhancement:
        """Add Reference data as a raw enhancement."""
        raw_enhancement_data = ref_to_import.copy()

        # Remove any keys that should be excluded
        for exclude in self.raw_enhancement_excludes:
            raw_enhancement_data.pop(exclude, None)

        return RawEnhancement(
            source_export_date=self.source_export_date,
            description=self.data_description,
            metadata=raw_enhancement_metadata,
            data=raw_enhancement_data,
        )

    def _create_annotation_enhancement(self) -> EnhancementContent | None:
        if not self.tags:
            return None
        annotations = []
        for tag in self.tags:
            # Tags are in the format <scheme>/<label>[@<score>], e.g.
            # "domain-inclusion/hpv@0.9".
            scheme_label, _, score = tag.partition("@")
            scheme, _, label = scheme_label.partition("/")
            annotations.append(
                BooleanAnnotation(
                    annotation_type=AnnotationType.BOOLEAN,
                    scheme=scheme,
                    label=label,
                    value=True,
                    score=float(score) if score else None,
                )
            )
        return AnnotationEnhancement(
            annotations=annotations,
        )

    def parse_references(
        self,
        data: dict,
        source: str | None = None,
        robot_version: str | None = None,
    ) -> tuple[list[ReferenceFileInput], list[dict]]:
        """
        Parse an EPPI JSON export dict and return a list of ReferenceFileInput objects.

        Args:
            data (dict): Parsed EPPI JSON export data.
            source (str | None): Optional source string for deduplication/provenance.
            robot_version (str | None): Optional robot version string for provenance.
            Defaults to parser version.

        Returns:
            list[ReferenceFileInput]: List of parsed references from the data.

        """
        parser_source = source if source is not None else self.parser_source
        raw_enhancement_metadata = self._raw_enhancement_metadata(data)

        references = []
        failed_refs = []
        for ref_to_import in data.get("References", []):
            try:
                enhancement_contents = [
                    content
                    for content in [
                        self._parse_abstract_enhancement(ref_to_import),
                        self._parse_bibliographic_enhancement(ref_to_import),
                        self._create_annotation_enhancement(),
                    ]
                    if content
                ]

                if self.include_raw_data:
                    enhancement_contents.append(
                        self._parse_raw_enhancement(
                            ref_to_import=ref_to_import,
                            raw_enhancement_metadata=raw_enhancement_metadata,
                        )
                    )

                enhancements = [
                    EnhancementFileInput(
                        source=parser_source,
                        visibility=Visibility.PUBLIC,
                        content=content,
                        robot_version=robot_version,
                    )
                    for content in enhancement_contents
                ]

                references.append(
                    ReferenceFileInput(
                        visibility=Visibility.PUBLIC,
                        identifiers=self._parse_identifiers(
                            ref_to_import=ref_to_import
                        ),
                        enhancements=enhancements,
                    )
                )

            except ExternalIdentifierNotFoundError:
                failed_refs.append(ref_to_import)

        return references, failed_refs

    def parse_enhancements(
        self,
        data: dict,
        source: str,
        robot_version: str | None = None,
    ) -> list[Enhancement]:
        """
        Parse an EPPI JSON export dict into raw enhancements for existing references.

        Each reference in the export must carry the id of the destiny reference it
        codes in its URL field, e.g.
        https://data.evidence-repository.org/esea/references/019f880e-2c39-7138-a387-221808f02d98

        Args:
            data (dict): Parsed EPPI JSON export data.
            source (str): Source string for deduplication/provenance.
            robot_version (str | None): Optional robot version string for provenance.

        Returns:
            list[Enhancement]: One raw enhancement per reference in the export.

        Raises:
            ReferenceIdNotFoundError: If any reference's URL field holds no
                destiny reference id the whole export is rejected.

        """
        if not self.include_raw_data:
            msg = "Cannot parse enhancements without include_raw_data set."
            raise RuntimeError(msg)

        raw_enhancement_metadata = self._raw_enhancement_metadata(data)

        enhancements = []
        unidentified_refs = []
        for ref_to_import in data.get("References", []):
            reference_id = self._parse_reference_id(ref_to_import)
            if not reference_id:
                unidentified_refs.append(ref_to_import)
                continue

            enhancements.append(
                Enhancement(
                    reference_id=reference_id,
                    source=source,
                    visibility=Visibility.PUBLIC,
                    robot_version=robot_version,
                    content=self._parse_raw_enhancement(
                        ref_to_import=ref_to_import,
                        raw_enhancement_metadata=raw_enhancement_metadata,
                    ),
                )
            )

        if unidentified_refs:
            unidentified = ", ".join(
                f"ItemId {ref.get('ItemId')} (URL: {ref.get('URL') or None})"
                for ref in unidentified_refs
            )
            msg = (
                f"No destiny reference id found in the URL field of "
                f"{len(unidentified_refs)} reference(s): {unidentified}."
            )
            raise ReferenceIdNotFoundError(detail=msg)

        return enhancements
