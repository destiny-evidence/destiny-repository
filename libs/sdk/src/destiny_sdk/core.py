"""Core data models for communicating with the DESTINY Repo."""

from enum import Enum, StrEnum
from typing import Annotated, Literal

from pydantic import (
    UUID4,
    AwareDatetime,
    BaseModel,
    Field,
    HttpUrl,
    PastDate,
)


class ExternalIdentifierBase(BaseModel):
    """The base class for external identifiers."""

    id: str


class PubmedIdentifier(ExternalIdentifierBase):
    """An external identifier which refers to a reference using a PubMed ID."""

    id: str
    type: Literal["pmid"]


class DoiIdentifier(ExternalIdentifierBase):
    """An external identifier which refers to a reference using a DOI."""

    id: str
    type: Literal["doi"]


class OpenAlexIdentifier(ExternalIdentifierBase):
    """An external identifier which refers to a reference using an OpenAlex work ID."""

    id: str
    type: Literal["open_alex"]


class OtherIdentifier(ExternalIdentifierBase):
    """An external identifier not otherwise defined by the repository."""

    id: str
    type: Literal["other"]
    other_identifier_type: str


ExternalIdentifierType = Annotated[
    DoiIdentifier | PubmedIdentifier | OpenAlexIdentifier | OtherIdentifier,
    Field(discriminator="type"),
]


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


class BibliographicMetadataEnhancement(BaseModel):
    """
    An enhancement which is made up of bibliographic metadata.

    Generally this will be sourced from a database such as OpenAlex or similar.
    For directly contributed references, these may not be complete.
    """

    enhancement_type: Literal["Bibliographic"]
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


class LocationEnhancement(BaseModel):
    """
    An enhancement which describes locations where this reference can be found.

    This maps closely (almost exactly) to OpenAlex's locations.
    """

    enhancement_type: Literal["location"] = "location"
    locations: list[Location] = Field(
        description="A list of locations where this reference can be found."
    )


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


class AnnotationEnhancement(BaseModel):
    """An enhancement which is composed of a list of Annotations."""

    enhancement_type: Literal["annotation"] = "annotation"
    annotations: list[Annotation]


EnhancementContent = Annotated[
    AnnotationEnhancement | LocationEnhancement | BibliographicMetadataEnhancement,
    Field(discriminator="enhancement_type" ""),
]


class EnhancementBase(BaseModel):
    """The base model for Enhancements, excluding creation-time fields."""

    source: str
    visibility: str
    processor_version: str
    content_version: str
    content: EnhancementContent


class EnhancementCreate(EnhancementBase):
    """The model for parameters required to create an enhancement."""

    reference_id: UUID4 = Field(
        description="The ID of the reference to create the enhancement against"
    )


class EnhancementRead(EnhancementBase):
    """The model for a created enhancement."""

    id: UUID4
    created_at: AwareDatetime
    updated_at: AwareDatetime


class EnhancementRequestCreate(BaseModel):
    """The model for requesting an enhancement on specific reference."""

    reference_id: UUID4 = Field(
        description="The ID of the reference to create the enhancement against"
    )

    robot_id: UUID4 = Field(
        description="The robot to be used to create the enhancement."
    )

    enhancement_parameters: dict | None = Field(
        default=None, description="Infromation needed to create the enhancement. TBC."
    )


class EnhancementRequestRead(BaseModel):
    """The model for an enhancement request."""

    id: UUID4
    reference_id: UUID4 = Field(description="The ID of the reference to be enhanced.")
    robot_id: UUID4 = Field(
        description="The robot to be used to create the enhancement."
    )
    request_status: str = Field(
        description="The status of the request to create an enhancement",
    )
    enhancement_parameters: dict | None = Field(
        default=None, description="Additional parameters to pass through to the robot"
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the enhancement process",
    )


class EnhancementRequestStatusRead(BaseModel):
    """The model for the status of an enhancement request."""

    id: UUID4
    request_status: str = Field(
        description="The status of the request to create an enhancement",
    )
    error: str | None = Field(
        default=None,
        description="Error encountered during the enhancement process",
    )


class Reference(BaseModel):
    """
    The base model stored in the repository.

    A reference does not contain any data by itself, but connects enhancements
    and identifiers.
    """

    id: UUID4
    identifiers: list[ExternalIdentifierType]
    enhancements: list[EnhancementRead] | None
