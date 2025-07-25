"""Parser for a EPPI JSON export file."""

import json
from pathlib import Path
from typing import Any

from destiny_sdk.enhancements import (
    AbstractContentEnhancement,
    AbstractProcessType,
    AuthorPosition,
    Authorship,
    BibliographicMetadataEnhancement,
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


def _parse_identifiers(ref_to_import: dict[str, Any]) -> list[ExternalIdentifier]:
    """
    Parse the identifiers from a reference to import.

    Args:
        ref_to_import: The reference to import.

    Returns:
        A list of ExternalIdentifier objects.

    """
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
    ref_to_import: dict[str, Any],
) -> EnhancementContent | None:
    """
    Parse the abstract from a reference to import.

    Args:
        ref_to_import: The reference to import.

    Returns:
        An EnhancementContent object or None.

    """
    if abstract := ref_to_import.get("Abstract"):
        return AbstractContentEnhancement(
            process=AbstractProcessType.OTHER,
            abstract=abstract,
        )
    return None


def _parse_bibliographic_enhancement(
    ref_to_import: dict[str, Any],
) -> EnhancementContent | None:
    """
    Parse the bibliographic metadata from a reference to import.

    Args:
        ref_to_import: The reference to import.

    Returns:
        An EnhancementContent object or None.

    """
    title = ref_to_import.get("Title")
    publication_year = (
        int(year) if (year := ref_to_import.get("Year")) and year.isdigit() else None
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


def parse_file(file_path: Path) -> list[ReferenceFileInput]:
    """
    Parse a EPPI JSON export file and return a list of references.

    Args:
        file_path: The path to the EPPI JSON export file.

    Returns:
        A list of ReferenceFileInput objects.

    """
    with file_path.open() as f:
        data = json.load(f)

    references = []
    for ref_to_import in data.get("References", []):
        enhancement_contents = [
            content
            for content in [
                _parse_abstract_enhancement(ref_to_import),
                _parse_bibliographic_enhancement(ref_to_import),
            ]
            if content
        ]

        enhancements = [
            EnhancementFileInput(
                source="eppi_export",
                visibility=Visibility.PUBLIC,
                content=content,
                enhancement_type=content.enhancement_type,
            )
            for content in enhancement_contents
        ]

        references.append(
            ReferenceFileInput(
                visibility=Visibility.PUBLIC,
                identifiers=_parse_identifiers(ref_to_import),
                enhancements=enhancements,
            )
        )
    return references
