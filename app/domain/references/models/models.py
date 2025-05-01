"""Models associated with references."""

import re
import uuid
from abc import ABC
from enum import Enum, StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PastDate,
    model_validator,
)

from app.domain.base import DomainBaseModel, SQLAttributeMixin
from app.utils.regex import RE_DOI, RE_OPEN_ALEX_IDENTIFIER
from app.utils.types import JSON


class Visibility(StrEnum):
    """
    The visibility of a data element in the repository.

    This is used to manage whether information should be publicly available or
    restricted (generally due to copyright constraints from publishers).

    TODO: Implement data governance layer to manage this.

    **Allowed values**:

    - `public`: Visible to the general public without authentication.
    - `restricted`: Requires authentication to be visible.
    - `hidden`: Is not visible, but may be passed to data mining processes.
    """

    PUBLIC = "public"
    RESTRICTED = "restricted"
    HIDDEN = "hidden"


class ExternalIdentifierType(StrEnum):
    """
    The type of identifier used to identify a reference.

    This is used to identify the type of identifier used in the `ExternalIdentifier`
    class.
    **Allowed values**:
    - `doi`: A DOI (Digital Object Identifier) which is a unique identifier for a
    document.
    - `pmid`: A PubMed ID which is a unique identifier for a document in PubMed.
    - `openalex`: An OpenAlex ID which is a unique identifier for a document in
    OpenAlex.
    - `other`: Any other identifier not defined. This should be used sparingly.
    """

    DOI = "doi"
    PM_ID = "pm_id"
    OPEN_ALEX = "open_alex"
    OTHER = "other"


class EnhancementType(StrEnum):
    """
    The type of enhancement.

    This is used to identify the type of enhancement in the `Enhancement` class.

    **Allowed values**:
    - `bibliographic`: Bibliographic metadata.
    - `abstract`: The abstract of a reference.
    - `annotation`: A free-form enhancement for tagging with labels.
    - `locations`: Locations where the reference can be found.
    """

    BIBLIOGRAPHIC = "bibliographic"
    ABSTRACT = "abstract"
    ANNOTATION = "annotation"
    LOCATION = "location"


class ExternalIdentifierBase(DomainBaseModel):
    """
    Base class for external identifiers.

    This is used to identify a reference in an external system.
    """

    identifier_type: ExternalIdentifierType = Field(
        description="The type of identifier used."
    )
    identifier: str = Field(description="The identifier itself.")
    other_identifier_name: str | None = Field(
        None,
        description="""
The name of the undocumented identifier type. This should be consistent to allow
later consolidation into a documented identifier type. This should only be used
if identifier_type is `other`.
""",
    )

    @model_validator(mode="after")
    def validate_other_identifier_name(self) -> Self:
        """
        Validate that the other_identifier_name is set correctly.

        It should be populated if and only if the identifier_type is `other`.
        """
        if self.identifier_type == ExternalIdentifierType.OTHER:
            if not self.other_identifier_name:
                msg = """
                other_identifier_name must be provided when identifier_type is 'other'
                """
                raise ValueError(msg)
        elif self.other_identifier_name:
            msg = """
                other_identifier_name must be empty when identifier_type is not 'other'"
                """
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_identifier_format(self) -> Self:
        """Validate the format of the identifier according to the identifier type."""
        if self.identifier_type == ExternalIdentifierType.DOI and not re.match(
            RE_DOI, self.identifier, re.IGNORECASE
        ):
            # TODO(Adam): consider validating against DOI itself
            # https://github.com/destiny-evidence/destiny-repository/issues/33
            msg = "The provided DOI is not in a valid format."
            raise ValueError(msg)
        if (
            self.identifier_type == ExternalIdentifierType.PM_ID
            and not self.identifier.isdigit()
        ):
            msg = "PM ID must be an integer."
            raise ValueError(msg)
        if self.identifier_type == ExternalIdentifierType.OPEN_ALEX and not re.match(
            RE_OPEN_ALEX_IDENTIFIER, self.identifier
        ):
            msg = "The provided OpenAlex ID is not in a valid format."
            raise ValueError(msg)
        return self


class ExternalIdentifier(ExternalIdentifierBase, SQLAttributeMixin):
    """External identifier model with database attributes included."""

    reference_id: uuid.UUID = Field(
        description="The ID of the reference this identifier identifies."
    )
    reference: "Reference | None" = Field(
        None,
        description="The reference this identifier identifies.",
    )


class ExternalIdentifierCreate(ExternalIdentifierBase):
    """Input for creating an external identifier."""


class ExternalIdentifierSearch(ExternalIdentifierBase):
    """Input for search on external identifiers."""


class ExternalIdentifierParseResult(BaseModel):
    """Result of an attempt to parse an external identifier."""

    external_identifier: ExternalIdentifierCreate | None = Field(
        None, description="The external identifier to create"
    )
    error: str | None = Field(
        None,
        description="Error encountered during the parsing process",
    )


class ReferenceBase(DomainBaseModel):
    """
    Base class for references.

    References do not carry data themselves but are used to tie together
    identifiers and enhancements.
    """

    visibility: Visibility = Field(
        Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )


class Reference(ReferenceBase, SQLAttributeMixin):
    """Reference model with database attributes included."""

    identifiers: list[ExternalIdentifier] | None = Field(
        None,
        description="A list of `ExternalIdentifiers` for the Reference",
    )
    enhancements: list["Enhancement"] | None = Field(
        None,
        description="A list of enhancements for the reference",
    )

    @classmethod
    def from_create(
        cls, reference_create: "ReferenceCreate", reference_id: uuid.UUID | None = None
    ) -> Self:
        """Create a reference including id hydration."""
        reference = cls(
            visibility=reference_create.visibility,
        )
        if reference_id:
            reference.id = reference_id
        reference.identifiers = [
            ExternalIdentifier(**identifier.model_dump(), reference_id=reference.id)
            for identifier in reference_create.identifiers or []
        ]
        reference.enhancements = [
            Enhancement(**enhancement.model_dump(), reference_id=reference.id)
            for enhancement in reference_create.enhancements or []
        ]
        return reference


class ReferenceCreate(ReferenceBase):
    """Input for creating a reference."""

    identifiers: list[ExternalIdentifierCreate] = Field(
        description="A list of `ExternalIdentifiers` for the Reference"
    )
    enhancements: list["EnhancementCreate"] = Field(
        default_factory=list,
        description="A list of enhancements for the reference",
    )


class ReferenceCreateInputValidator(ReferenceBase):
    """Validator for the top-level schema of a reference creation input."""

    identifiers: list[JSON] = Field(min_length=1)
    enhancements: list[JSON] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class EnhancementContentBase(BaseModel, ABC):
    """
    Base class for enhancement content.

    N.B. must define an `enhancement_type: EnhancementType` property to be used
    as a discriminator.
    (Not provided as an abstract property thanks to https://github.com/pydantic/pydantic/discussions/2410,
    runtime errors are sufficient to ensure implemented).
    """


class AuthorPosition(str, Enum):
    """
    The position of an author in a list of authorships.

    Maps to the data from OpenAlex.

    **Allowed values**:
    - `first`: The first author.
    - `middle`: Any middle author
    - `last`: The last author
    """

    FIRST = "first"
    MIDDLE = "middle"
    LAST = "last"


class Authorship(BaseModel):
    """
    Represents a single author and their association with a reference.

    This is a simplification of the OpenAlex [Authorship
    object](https://docs.openalex.org/api-entities/works/work-object/authorship-object)
    for our purposes.
    """

    display_name: str = Field(description="The display name of the author.")
    orcid: str = Field(description="The ORCid of the author.")
    position: AuthorPosition = Field(
        description="The position of the author within the list of authors."
    )


class BibliographicMetadataEnhancement(EnhancementContentBase):
    """
    An enhancement which is made up of bibliographic metadata.

    Generally this will be sourced from a database such as OpenAlex or similar.
    For directly contributed references, these may not be complete.
    """

    enhancement_type: Literal[EnhancementType.BIBLIOGRAPHIC] = (
        EnhancementType.BIBLIOGRAPHIC
    )
    authorship: list[Authorship] | None = Field(
        None,
        description="A list of `Authorships` belonging to this reference.",
    )
    cited_by_count: int | None = Field(
        None,
        description="""
(From OpenAlex) The number of citations to this work. These are the times that
other works have cited this work
""",
    )
    created_date: PastDate | None = Field(
        None, description="The ISO8601 date this metadata record was created"
    )
    publication_date: PastDate | None = Field(
        None, description="The date which the version of record was published."
    )
    publication_year: int | None = Field(
        None, description="The year in which the version of record was published."
    )
    publisher: str | None = Field(
        None,
        description="The name of the entity which published the version of record.",
    )
    title: str | None = Field(None, description="The title of the reference.")


class AbstractProcessType(StrEnum):
    """
    The process used to acquyire the abstract.

    **Allowed values**:
    - `uninverted`
    - `closed_api`
    - `other`
    """

    UNINVERTED = "uninverted"
    CLOSED_API = "closed_api"
    OTHER = "other"


class AbstractContentEnhancement(BaseModel):
    """
    An enhancement which is specific to the abstract of a reference.

    This is separate from the `BibliographicMetadata` for two reasons:

    1. Abstracts are increasingly missing from sources like OpenAlex, and may be
    backfilled from other sources, without the bibliographic metadata.
    2. They are also subject to copyright limitations in ways which metadata are
    not, and thus need separate visibility controls.
    """

    enhancement_type: Literal[EnhancementType.ABSTRACT] = EnhancementType.ABSTRACT
    process: AbstractProcessType = Field(
        description="The process used to acquire the abstract."
    )
    abstract: str = Field(description="The abstract of the reference.")


class Annotation(BaseModel):
    """
    An annotation is a way of tagging the content with a label of some kind.

    This class will probably be broken up in the future, but covers most of our
    initial cases.
    """

    annotation_type: str = Field(
        description="An identifier for the type of annotation",
        examples=["openalex:topic", "pubmed:mesh"],
    )
    label: str = Field(
        description="A high level label for this annotation like the name of the topic",
    )
    data: dict = Field(
        description="""
An object representation of the annotation including any confidence scores or
descriptions.
""",
    )


class AnnotationEnhancement(EnhancementContentBase):
    """An enhancement which is composed of a list of Annotations."""

    enhancement_type: Literal[EnhancementType.ANNOTATION] = EnhancementType.ANNOTATION
    annotations: list[Annotation]


class DriverVersion(StrEnum):
    """
    The version based on the DRIVER guidelines versioning scheme.

    (Borrowed from OpenAlex)

    Allowed values:
    - `publishedVersion`: The document's version of record. This is the most
    authoritative version.
    - `acceptedVersion`: The document after having completed peer review and being
    officially accepted for publication. It will lack publisher formatting, but the
    content should be interchangeable with the that of the publishedVersion.
    - `submittedVersion`: the document as submitted to the publisher by the authors, but
    before peer-review. Its content may differ significantly from that of the accepted
    article.
    """

    PUBLISHED_VERSION = "publishedVersion"
    ACCEPTED_VERSION = "acceptedVersion"
    SUBMITTED_VERSION = "submittedVersion"
    OTHER = "other"


class Location(BaseModel):
    """
    A location where a reference can be found.

    This maps almost completely to the OpenAlex
    [Location object](https://docs.openalex.org/api-entities/works/work-object/location-object)
    """

    is_oa: bool | None = Field(
        None,
        description="""
(From OpenAlex): True if an Open Access (OA) version of this work is available
at this location. May be left as null if this is unknown (and thus)
treated effectively as `false`.
""",
    )
    version: DriverVersion | None = Field(
        None,
        description="""
The version (according to the DRIVER versioning scheme) of this location.
""",
    )
    landing_page_url: HttpUrl | None = Field(
        None, description="(From OpenAlex): The landing page URL for this location."
    )
    pdf_url: HttpUrl | None = Field(
        None,
        description="""
(From OpenAlex): A URL where you can find this location as a PDF.
""",
    )
    license: str | None = Field(
        None,
        description="""
(From OpenAlex): The location's publishing license. This can be a Creative
Commons license such as cc0 or cc-by, a publisher-specific license, or null
which means we are not able to determine a license for this location.
""",
    )
    extra: dict | None = Field(
        None, description="Any extra metadata about this location"
    )


class LocationEnhancement(EnhancementContentBase):
    """
    An enhancement which describes locations where this reference can be found.

    This maps closely (almost exactly) to OpenAlex's locations.
    """

    enhancement_type: Literal[EnhancementType.LOCATION] = EnhancementType.LOCATION
    locations: list[Location] = Field(
        description="A list of locations where this reference can be found."
    )


EnhancementContentType = (
    BibliographicMetadataEnhancement
    | AbstractContentEnhancement
    | AnnotationEnhancement
    | LocationEnhancement
)


class EnhancementBase(DomainBaseModel):
    """
    Base class for enhancements.

    An enhancement is any data about a reference which is in addition to the
    identifiers of that reference. Anything which is useful is generally an
    enhancement. They will be flattened and composed for search and access.

    This class should not be used directly, but inherited from to define new
    enhancement classes.
    """

    source: str = Field(
        description="The enhancement source for tracking provenance.",
    )
    visibility: Visibility = Field(
        description="The level of visibility of the enhancement"
    )
    processor_version: str | None = Field(
        None,
        description="The version of the processor that generated the content.",
    )
    content_version: uuid.UUID = Field(
        description="""
        UUID regenerated when the content changes.
        Can be used to identify when content has changed.
        """,
        default_factory=uuid.uuid4,
    )
    enhancement_type: EnhancementType = Field(
        description="The type of enhancement.",
    )

    content: Annotated[
        EnhancementContentType,
        Field(
            discriminator="enhancement_type",
            description="The content of the enhancement.",
        ),
    ]

    @model_validator(mode="after")
    def check_enhancement_type(self) -> Self:
        """Assert that the enhancement type of the content matches the parent."""
        if self.content.enhancement_type != self.enhancement_type:
            msg = "content enhancement_type must match parent enhancement_type"
            raise ValueError(msg)
        return self


class Enhancement(EnhancementBase, SQLAttributeMixin):
    """Enhancement model with database attributes included."""

    reference_id: uuid.UUID = Field(
        description="The ID of the reference this enhancement is associated with."
    )

    reference: Reference | None = Field(
        None,
        description="The reference this enhancement is associated with.",
    )


class EnhancementCreate(EnhancementBase):
    """Input for creating an enhancement."""


class EnhancementParseResult(BaseModel):
    """Result of an attempt to parse an enhancement."""

    enhancement: EnhancementCreate | None = Field(
        None,
        description="The enhancement to create",
    )
    error: str | None = Field(
        None,
        description="Error encountered during the parsing process",
    )


class ReferenceCreateResult(BaseModel):
    """
    Result of an attempt to create a reference.

    If reference is None, no reference was created and errors will be populated.
    If reference exists and there are errors, the reference was created but there
    were errors in the hydration.
    If reference exists and there are no errors, the reference was created and all
    enhancements/identifiers were hydrated successfully from the input.
    """

    reference: Reference | None = Field(
        None,
        description="""
    The created reference.
    If None, no reference was created.
    """,
    )
    errors: list[str] = Field(
        default_factory=list,
        description="A list of errors encountered during the creation process",
    )

    @property
    def error_str(self) -> str | None:
        """Return a string of errors if they exist."""
        return "\n\n".join(e.strip() for e in self.errors) if self.errors else None
