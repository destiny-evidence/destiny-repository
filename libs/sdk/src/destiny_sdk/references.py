"""Reference classes for the Destiny SDK."""

from typing import Self, Generator

from pydantic import UUID4, BaseModel, Field, TypeAdapter

from destiny_sdk.core import _JsonlFileInputMixIn
from destiny_sdk.identifiers import ExternalIdentifier, ExternalIdentifierType
from destiny_sdk.visibility import Visibility
from destiny_sdk.enhancements import (
    Enhancement,
    EnhancementFileInput,
    EnhancementType,
    AnnotationType,
    Annotation,
    BibliographicMetadataEnhancement,
)

external_identifier_adapter = TypeAdapter(ExternalIdentifier)


class Reference(_JsonlFileInputMixIn, BaseModel):
    """Core reference class."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    id: UUID4 = Field(
        description="The ID of the reference",
    )
    identifiers: list[ExternalIdentifier] | None = Field(
        default=None,
        description="A list of `ExternalIdentifiers` for the Reference",
    )
    enhancements: list[Enhancement] | None = Field(
        default=None,
        description="A list of enhancements for the reference",
    )

    @classmethod
    def from_es(cls, es_reference: dict) -> Self:
        """Create a Reference from an Elasticsearch document."""
        return cls(
            id=es_reference["_id"],
            visibility=Visibility(es_reference["_source"]["visibility"]),
            identifiers=[
                external_identifier_adapter.validate_python(identifier)
                for identifier in es_reference["_source"].get("identifiers", [])
            ],
            enhancements=[
                Enhancement.model_validate(
                    enhancement | {"reference_id": es_reference["_id"]},
                )
                for enhancement in es_reference["_source"].get("enhancements", [])
            ],
        )

    def _get_id(self, kind: ExternalIdentifierType) -> str | None:
        """Convenience method to fetch identifier enhancements."""
        for identifier in (self.identifiers or []):
            if identifier.kind == kind:
                return identifier.identifier
        return None

    @property
    def openalex_id(self) -> str | None:
        """The OpenAlex ID of the reference. If multiple OpenAlex IDs are present, return first one."""
        return self._get_id(kind=ExternalIdentifierType.OPEN_ALEX)

    @property
    def doi(self) -> str | None:
        """The DOI of the reference. If multiple DOIs are present, return first one."""
        return self._get_id(kind=ExternalIdentifierType.DOI)

    @property
    def pubmed_id(self) -> str | None:
        """The pubmed ID of the reference. If multiple pubmed IDs are present, return first one."""
        return self._get_id(kind=ExternalIdentifierType.PM_ID)

    @property
    def abstract(self) -> str | None:
        """The abstract of the reference. If multiple abstracts are present, return first one."""
        for enhancement in (self.enhancements or []):
            if enhancement.content.enhancement_type == EnhancementType.ABSTRACT:
                return enhancement.content.abstract
        return None

    @property
    def publication_year(self) -> int | None:
        """The publication year of the reference. If multiple publication years are present, return first one."""
        for meta in self.bibliographics():
            if meta.publication_year is not None:
                return meta.publication_year
        return None

    @property
    def title(self) -> str | None:
        """The title of the reference. If multiple titles are present, return first one."""
        for meta in self.bibliographics():
            if meta.title is not None:
                return meta.title
        return None

    def bibliographics(self) -> Generator[BibliographicMetadataEnhancement, None, None]:
        """Convenience method to access bibliographic metadata enhancements."""
        for enhancement in (self.enhancements or []):
            if enhancement.content.enhancement_type == EnhancementType.BIBLIOGRAPHIC:
                yield enhancement.content

    def annotations(
            self,
            source: str | None = None,
            annotation_type: AnnotationType | None = None,
            scheme: str | None = None,
            label: str | None = None,
    ) -> Generator[Annotation, None, None]:
        """Generates a list of annotations for the given filters.

        :param source: Optional filter for Enhancement.source
        :param annotation_type: Optional filter for AnnotationEnhancement.annotation_type
        :param scheme: Optional filter for Annotation.scheme
        :param label: Optional filter for Annotation.label
        """
        for enhancement in (self.enhancements or []):
            if enhancement.content.enhancement_type == EnhancementType.ANNOTATION:
                if source is not None and enhancement.source != source:
                    continue
                for annotation in enhancement.content.annotations:
                    if annotation_type is not None and annotation.annotation_type != annotation_type:
                        continue
                    if scheme is not None and annotation.scheme != scheme:
                        continue
                    if label is not None and annotation.label != label:
                        continue
                    yield annotation

    def is_true(
            self,
            source: str | None = None,
            scheme: str | None = None,
            label: str | None = None,
    ) -> bool | None:
        """Convenience method to check if a specific annotation exists and is true.

        :param source: Optional filter for Enhancement.source
        :param scheme: Optional filter for Annotation.scheme
        :param label: Optional filter for Annotation.label
        :return: Returns the boolean value for the first annotation matching the filters or None if nothing is found.
        """
        for annotation in self.annotations(
                source=source,
                annotation_type=AnnotationType.BOOLEAN,
                scheme=scheme,
                label=label,
        ):
            return annotation.value
        return None


class ReferenceFileInput(_JsonlFileInputMixIn, BaseModel):
    """Enhancement model used to marshall a file input."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list[ExternalIdentifier] | None = Field(
        default=None,
        description="A list of `ExternalIdentifiers` for the Reference",
    )
    enhancements: list[EnhancementFileInput] | None = Field(
        default=None,
        description="A list of enhancements for the reference",
    )
