"""Parser for a EPPI JSON export file."""

from datetime import datetime
from typing import Any

from pydantic import ValidationError

from destiny_sdk.enhancements import (
    AbstractContentEnhancement,
    AbstractProcessType,
    AnnotationEnhancement,
    AnnotationType,
    AuthorPosition,
    Authorship,
    BibliographicMetadataEnhancement,
    BooleanAnnotation,
    EnhancementContent,
    EnhancementFileInput,
    RawEnhancement,
)
from destiny_sdk.identifiers import (
    DOIIdentifier,
    ERICIdentifier,
    ExternalIdentifier,
    OpenAlexIdentifier,
    ProQuestIdentifier,
)
from destiny_sdk.parsers.exceptions import ExternalIdentifierNotFoundError
from destiny_sdk.references import ReferenceFileInput
from destiny_sdk.visibility import Visibility


class EPPIParser:
    """
    Parser for an EPPI JSON export file.

    See example here: https://eppi.ioe.ac.uk/cms/Portals/35/Maps/Examples/example_orignal.json
    """

    version = "2.0"

    def __init__(
        self,
        *,
        tags: list[str] | None = None,
        include_raw_data: bool = False,
        source_export_date: datetime | None = None,
        data_description: str | None = None,
        raw_enhancement_excludes: list[str] | None = None,
    ) -> None:
        """
        Initialize the EPPIParser with optional tags.

        Args:
            tags (list[str] | None): Optional list of tags to annotate references.

        """
        self.tags = tags or []
        self.parser_source = f"destiny_sdk.eppi_parser@{self.version}"
        self.include_raw_data = include_raw_data
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
        identifiers = []
        if doi := ref_to_import.get("DOI"):
            doi_identifier = self._parse_doi(doi=doi)
            if doi_identifier:
                identifiers.append(doi_identifier)

        if url := ref_to_import.get("URL"):
            identifier = self._parse_url_to_identifier(url=url)
            if identifier:
                identifiers.append(identifier)

        if not identifiers:
            msg = (
                "No known external identifiers found for Reference data "
                f"with DOI: '{doi if doi else None}' "
                f"and URL: '{url if url else None}'."
            )
            raise ExternalIdentifierNotFoundError(detail=msg)

        return identifiers

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
        identifier_cls = None
        if "eric" in url:
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

    def _parse_raw_enhancement(
        self, ref_to_import: dict[str, Any], raw_enhancement_metadata: dict[str, Any]
    ) -> EnhancementContent | None:
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
        annotations = [
            BooleanAnnotation(
                annotation_type=AnnotationType.BOOLEAN,
                scheme=self.parser_source,
                label=tag,
                value=True,
            )
            for tag in self.tags
        ]
        return AnnotationEnhancement(
            annotations=annotations,
        )

    def parse_data(
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

        if self.include_raw_data:
            codesets = [codeset.get("SetId") for codeset in data.get("CodeSets", [])]
            raw_enhancement_metadata = {"codeset_ids": codesets}

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
                    raw_enhancement = self._parse_raw_enhancement(
                        ref_to_import=ref_to_import,
                        raw_enhancement_metadata=raw_enhancement_metadata,
                    )

                    if raw_enhancement:
                        enhancement_contents.append(raw_enhancement)

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
