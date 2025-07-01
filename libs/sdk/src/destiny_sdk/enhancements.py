"""Enhancement classes for the Destiny Repository."""

import datetime
from enum import StrEnum, auto
from typing import Annotated, Literal

from pydantic import UUID4, BaseModel, Field, HttpUrl

from destiny_sdk.core import _JsonlFileInputMixIn
from destiny_sdk.visibility import Visibility


class EnhancementType(StrEnum):
    """
    The type of enhancement.

    This is used to identify the type of enhancement in the `Enhancement` class.

    **Allowed values**:
    - `bibliographic`: Bibliographic metadata.
    - `abstract`: The abstract of a reference.
    - `annotation`: A free-form enhancement for tagging with labels.
    - `locations`: Locations where the reference can be found.
    - `full_text`: The full text of the reference. (To be implemeted)
    """

    BIBLIOGRAPHIC = auto()
    ABSTRACT = auto()
    ANNOTATION = auto()
    LOCATION = auto()
    FULL_TEXT = auto()


class AuthorPosition(StrEnum):
    """
    The position of an author in a list of authorships.

    Maps to the data from OpenAlex.

    **Allowed values**:
    - `first`: The first author.
    - `middle`: Any middle author
    - `last`: The last author
    """

    FIRST = auto()
    MIDDLE = auto()
    LAST = auto()


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

    enhancement_type: Literal[EnhancementType.BIBLIOGRAPHIC] = (
        EnhancementType.BIBLIOGRAPHIC
    )
    authorship: list[Authorship] | None = Field(
        default=None,
        description="A list of `Authorships` belonging to this reference.",
    )
    cited_by_count: int | None = Field(
        default=None,
        description="""
(From OpenAlex) The number of citations to this work. These are the times that
other works have cited this work
""",
    )
    created_date: datetime.date | None = Field(
        default=None, description="The ISO8601 date this metadata record was created"
    )
    publication_date: datetime.date | None = Field(
        default=None, description="The date which the version of record was published."
    )
    publication_year: int | None = Field(
        default=None,
        description="The year in which the version of record was published.",
    )
    publisher: str | None = Field(
        default=None,
        description="The name of the entity which published the version of record.",
    )
    title: str | None = Field(default=None, description="The title of the reference.")


class AbstractProcessType(StrEnum):
    """
    The process used to acquyire the abstract.

    **Allowed values**:
    - `uninverted`
    - `closed_api`
    - `other`
    """

    UNINVERTED = auto()
    CLOSED_API = auto()
    OTHER = auto()


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


class AnnotationType(StrEnum):
    """
    The type of annotation.

    This is used to identify the type of annotation in the `Annotation` class.

    **Allowed values**:
    - `boolean`: An annotation which is the boolean application of a label across a
    reference.
    - `score`: An annotation which is a score for a label across a reference,
    without a boolean value.
    """

    BOOLEAN = auto()
    SCORE = auto()


class ScoreAnnotation(BaseModel):
    """
    An annotation which represents the score for a label.

    This is similar to a BooleanAnnotation, but lacks a boolean determination
    as to the application of the label.
    """

    annotation_type: Literal[AnnotationType.SCORE] = AnnotationType.SCORE
    scheme: str = Field(
        description="An identifier for the scheme of annotation",
        examples=["openalex:topic", "pubmed:mesh"],
    )
    label: str = Field(
        description="A high level label for this annotation like the name of the topic",
    )
    score: float = Field(description="""Score for this annotation""")
    data: dict = Field(
        default_factory=dict,
        description=(
            "An object representation of the annotation including any confidence scores"
            " or descriptions."
        ),
    )


class BooleanAnnotation(BaseModel):
    """
    An annotation is a way of tagging the content with a label of some kind.

    This class will probably be broken up in the future, but covers most of our
    initial cases.
    """

    annotation_type: Literal[AnnotationType.BOOLEAN] = AnnotationType.BOOLEAN
    scheme: str = Field(
        description="An identifier for the scheme of the annotation",
        examples=["openalex:topic", "pubmed:mesh"],
    )
    label: str = Field(
        description="A high level label for this annotation like the name of the topic",
    )
    value: bool = Field(description="""Boolean flag for this annotation""")
    score: float | None = Field(
        None, description="A confidence score for this annotation"
    )
    data: dict = Field(
        default_factory=dict,
        description="""
An object representation of the annotation including any confidence scores or
descriptions.
""",
    )


#: Union type for all annotations.
Annotation = Annotated[
    BooleanAnnotation | ScoreAnnotation, Field(discriminator="annotation_type")
]


class AnnotationEnhancement(BaseModel):
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
        default=None,
        description="""
(From OpenAlex): True if an Open Access (OA) version of this work is available
at this location. May be left as null if this is unknown (and thus)
treated effectively as `false`.
""",
    )
    version: DriverVersion | None = Field(
        default=None,
        description="""
The version (according to the DRIVER versioning scheme) of this location.
""",
    )
    landing_page_url: HttpUrl | None = Field(
        default=None,
        description="(From OpenAlex): The landing page URL for this location.",
    )
    pdf_url: HttpUrl | None = Field(
        default=None,
        description="""
(From OpenAlex): A URL where you can find this location as a PDF.
""",
    )
    license: str | None = Field(
        default=None,
        description="""
(From OpenAlex): The location's publishing license. This can be a Creative
Commons license such as cc0 or cc-by, a publisher-specific license, or null
which means we are not able to determine a license for this location.
""",
    )
    extra: dict | None = Field(
        default=None, description="Any extra metadata about this location"
    )


class LocationEnhancement(BaseModel):
    """
    An enhancement which describes locations where this reference can be found.

    This maps closely (almost exactly) to OpenAlex's locations.
    """

    enhancement_type: Literal[EnhancementType.LOCATION] = EnhancementType.LOCATION
    locations: list[Location] = Field(
        description="A list of locations where this reference can be found."
    )


#: Union type for all enhancement content types.
EnhancementContent = Annotated[
    BibliographicMetadataEnhancement
    | AbstractContentEnhancement
    | AnnotationEnhancement
    | LocationEnhancement,
    Field(discriminator="enhancement_type"),
]


class Enhancement(_JsonlFileInputMixIn, BaseModel):
    """Core enhancement class."""

    id: UUID4 | None = Field(
        default=None,
        description=(
            "The ID of the enhancement. "
            "Populated by the repository when sending enhancements with references."
        ),
    )

    reference_id: UUID4 = Field(
        description="The ID of the reference this enhancement is associated with."
    )
    source: str = Field(
        description="The enhancement source for tracking provenance.",
    )
    visibility: Visibility = Field(
        description="The level of visibility of the enhancement"
    )
    robot_version: str | None = Field(
        default=None,
        description="The version of the robot that generated the content.",
    )
    derived_from: list[UUID4] | None = Field(
        default=None,
        description="List of enhancement IDs that this enhancement was derived from.",
    )
    content: Annotated[
        EnhancementContent,
        Field(
            discriminator="enhancement_type",
            description="The content of the enhancement.",
        ),
    ]


class EnhancementFileInput(BaseModel):
    """Enhancement model used to marshall a file input to new references."""

    source: str = Field(
        description="The enhancement source for tracking provenance.",
    )
    visibility: Visibility = Field(
        description="The level of visibility of the enhancement"
    )
    enhancement_type: EnhancementType = Field(description="The type of enhancement.")
    robot_version: str | None = Field(
        default=None,
        description="The version of the robot that generated the content.",
        # (Adam) Temporary alias for backwards compatibility for already prepared files
        # Next person who sees this can remove it :)
        alias="processor_version",
    )
    content: EnhancementContent = Field(
        discriminator="enhancement_type",
        description="The content of the enhancement.",
    )
