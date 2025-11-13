"""
Extended Reference SDK.

Extended Reference class for the Destiny SDK
with added experimental convenience methods and properties.
"""

from collections.abc import Generator
from typing import cast

from pydantic import BaseModel, Field

from destiny_sdk.enhancements import (
    Annotation,
    AnnotationType,
    BibliographicMetadataEnhancement,
    EnhancementType,
)
from destiny_sdk.identifiers import ExternalIdentifierType
from destiny_sdk.references import Reference


class LabsReference(BaseModel):
    """Experimental presenter class for Reference with added convenience methods."""

    reference: Reference = Field(
        ...,
        description="The core Reference object",
    )

    def _get_id(self, identifier_type: ExternalIdentifierType) -> str | int | None:
        """Fetch an identifier matching the given identifier_type."""
        for identifier in self.reference.identifiers or []:
            if identifier.identifier_type == identifier_type:
                return identifier.identifier
        return None

    @property
    def openalex_id(self) -> str | None:
        """Return an OpenAlex ID for the reference."""
        return cast(
            str | None, self._get_id(identifier_type=ExternalIdentifierType.OPEN_ALEX)
        )

    @property
    def doi(self) -> str | None:
        """Return a DOI for the reference."""
        return cast(
            str | None, self._get_id(identifier_type=ExternalIdentifierType.DOI)
        )

    @property
    def pubmed_id(self) -> int | None:
        """Return a pubmed ID for the reference."""
        return cast(
            int | None, self._get_id(identifier_type=ExternalIdentifierType.PM_ID)
        )

    @property
    def abstract(self) -> str | None:
        """Return an abstract for the reference."""
        for enhancement in self.reference.enhancements or []:
            if enhancement.content.enhancement_type == EnhancementType.ABSTRACT:
                return enhancement.content.abstract
        return None

    @property
    def publication_year(self) -> int | None:
        """Return a publication year for the reference."""
        for meta in self.it_bibliographics():
            if meta.publication_year is not None:
                return meta.publication_year
        return None

    @property
    def title(self) -> str | None:
        """The title of the reference. If multiple are present, return first one."""
        for meta in self.it_bibliographics():
            if meta.title is not None:
                return meta.title
        return None

    def it_bibliographics(
        self,
    ) -> Generator[BibliographicMetadataEnhancement, None, None]:
        """Iterate bibliographic enhancements."""
        for enhancement in self.reference.enhancements or []:
            if enhancement.content.enhancement_type == EnhancementType.BIBLIOGRAPHIC:
                yield enhancement.content

    def it_annotations(
        self,
        source: str | None = None,
        annotation_type: AnnotationType | None = None,
        scheme: str | None = None,
        label: str | None = None,
    ) -> Generator[Annotation, None, None]:
        """
        Iterate annotation enhancements for the given filters.

        :param source: Optional filter for Enhancement.source
        :param annotation_type: Optional filter for
                                AnnotationEnhancement.annotation_type
        :param scheme: Optional filter for Annotation.scheme
        :param label: Optional filter for Annotation.label
        """
        for enhancement in self.reference.enhancements or []:
            if enhancement.content.enhancement_type == EnhancementType.ANNOTATION:
                if source is not None and enhancement.source != source:
                    continue
                for annotation in enhancement.content.annotations:
                    if (
                        annotation_type is not None
                        and annotation.annotation_type != annotation_type
                    ):
                        continue
                    if scheme is not None and annotation.scheme != scheme:
                        continue
                    if label is not None and annotation.label != label:
                        continue
                    yield annotation

    def has_bool_annotation(
        self,
        source: str | None = None,
        scheme: str | None = None,
        label: str | None = None,
        expected_value: bool = True,  # noqa: FBT001, FBT002
    ) -> bool | None:
        """
        Check if a specific annotation exists and is true.

        :param source: Optional filter for Enhancement.source
        :param scheme: Optional filter for Annotation.scheme
        :param label: Optional filter for Annotation.label
        :param expected_value: Specify expected boolean annotation value
        :return: Returns the boolean value for the first annotation matching
                 the filters or None if nothing is found.
        """
        if scheme is None and label is None:
            msg = "Please use at least one of the optional scheme or label filters."
            raise AssertionError(msg)

        found_annotation = False
        for annotation in self.it_annotations(
            source=source,
            annotation_type=AnnotationType.BOOLEAN,
            scheme=scheme,
            label=label,
        ):
            if annotation.value == expected_value:
                return True
            found_annotation = True
        return False if found_annotation else None
