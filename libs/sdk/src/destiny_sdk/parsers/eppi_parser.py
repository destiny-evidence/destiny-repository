"""Parser for a EPPI JSON export file."""

from typing import Any

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
)
from destiny_sdk.identifiers import (
    DOIIdentifier,
    ExternalIdentifier,
    ExternalIdentifierType,
)
from destiny_sdk.references import ReferenceFileInput
from destiny_sdk.visibility import Visibility


class EPPIParser:
    """
    Parser for an EPPI JSON export file.

    See example here: https://eppi.ioe.ac.uk/cms/Portals/35/Maps/Examples/example_orignal.json
    """

    version = "1.0"

    def __init__(self, tags: list[str] | None = None) -> None:
        """
        Initialize the EPPIParser with optional tags.

        Args:
            tags (list[str] | None): Optional list of tags to annotate references.

        """
        self.tags = tags or []
        self.parser_source = f"destiny_sdk.eppi_parser@{self.version}"

    def _parse_identifiers(
        self, ref_to_import: dict[str, Any]
    ) -> list[ExternalIdentifier]:
        identifiers = []
        if doi := ref_to_import.get("DOI"):
            identifiers.append(
                DOIIdentifier(
                    identifier=doi,
                    identifier_type=ExternalIdentifierType.DOI,
                )
            )
        return identifiers

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
        self, data: dict, source: str | None = None, robot_version: str | None = None
    ) -> list[ReferenceFileInput]:
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
        references = []
        for ref_to_import in data.get("References", []):
            enhancement_contents = [
                content
                for content in [
                    self._parse_abstract_enhancement(ref_to_import),
                    self._parse_bibliographic_enhancement(ref_to_import),
                    self._create_annotation_enhancement(),
                ]
                if content
            ]

            enhancements = [
                EnhancementFileInput(
                    source=parser_source,
                    visibility=Visibility.PUBLIC,
                    content=content,
                    enhancement_type=content.enhancement_type,
                    robot_version=robot_version,
                )
                for content in enhancement_contents
            ]

            references.append(
                ReferenceFileInput(
                    visibility=Visibility.PUBLIC,
                    identifiers=self._parse_identifiers(ref_to_import),
                    enhancements=enhancements,
                )
            )
        return references
