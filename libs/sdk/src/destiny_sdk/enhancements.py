"""Enhancement classes for the Destiny Repository."""

import datetime
import json
from enum import StrEnum, auto
from typing import Annotated, Any, Literal, Self

from pydantic import UUID4, BaseModel, Field, HttpUrl, model_validator

from destiny_sdk.core import _JsonlFileInputMixIn
from destiny_sdk.identifiers import Identifier
from destiny_sdk.visibility import Visibility


class EnhancementType(StrEnum):
    """
    The type of enhancement.

    This is used to identify the type of enhancement in the `Enhancement` class.
    """

    BIBLIOGRAPHIC = auto()
    """Bibliographic metadata."""
    ABSTRACT = auto()
    """The abstract of a reference."""
    ANNOTATION = auto()
    """A free-form enhancement for tagging with labels."""
    LOCATION = auto()
    """Locations where the reference can be found."""
    REFERENCE_ASSOCIATION = auto()
    """Associations to other references."""
    RAW = auto()
    """A free form enhancement for arbitrary/unstructured data."""
    FULL_TEXT = auto()
    """The full text of the reference. (To be implemented)"""


class AuthorPosition(StrEnum):
    """
    The position of an author in a list of authorships.

    Maps to the data from OpenAlex.
    """

    FIRST = auto()
    """The first author."""
    MIDDLE = auto()
    """Any middle author."""
    LAST = auto()
    """The last author."""


class Authorship(BaseModel):
    """
    Represents a single author and their association with a reference.

    This is a simplification of the OpenAlex [Authorship
    object](https://docs.openalex.org/api-entities/works/work-object/authorship-object)
    for our purposes.
    """

    display_name: str = Field(
        description="The display name of the author. "
        "Expected format FIRSTNAME <MIDDLENAME> LASTNAME. "
        "Providing display_name in an unexpected format will affect search performance."
    )
    orcid: str | None = Field(default=None, description="The ORCid of the author.")
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
    updated_date: datetime.date | None = Field(
        default=None,
        description="The ISO8601 date of the last OpenAlex update to this metadata",
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

    @property
    def fingerprint(self) -> str:
        """
        The fingerprint of this bibliographic metadata enhancement.

        Excludes updated_at from the fingerprint calculation, meaning
        that two raw enhancements with identical data but different export dates
        will be considered the same.
        """
        return json.dumps(
            self.model_dump(mode="json", exclude={"updated_date"}, exclude_none=True),
            sort_keys=True,
        )


class AbstractProcessType(StrEnum):
    """The process used to acquire the abstract."""

    UNINVERTED = auto()
    """uninverted"""
    CLOSED_API = auto()
    """closed_api"""
    OTHER = auto()
    """other"""


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
    """

    BOOLEAN = auto()
    """An annotation which is the boolean application of a label across a reference."""
    SCORE = auto()
    """
    An annotation which is a score for a label across a reference, without a boolean
    value.
    """


class BaseAnnotation(BaseModel):
    """Base class for annotations, defining the minimal required fields."""

    scheme: str = Field(
        description="An identifier for the scheme of annotation",
        examples=["openalex:topic", "pubmed:mesh"],
        pattern=r"^[^/]+$",  # No slashes allowed
    )
    label: str = Field(
        description="A high level label for this annotation like the name of the topic",
    )

    @property
    def qualified_label(self) -> str:
        """The qualified label for this annotation."""
        return f"{self.scheme}/{self.label}"


class ScoreAnnotation(BaseAnnotation):
    """
    An annotation which represents the score for a label.

    This is similar to a BooleanAnnotation, but lacks a boolean determination
    as to the application of the label.
    """

    annotation_type: Literal[AnnotationType.SCORE] = AnnotationType.SCORE
    score: float = Field(description="""Score for this annotation""")
    data: dict = Field(
        default_factory=dict,
        description=(
            "An object representation of the annotation including any confidence scores"
            " or descriptions."
        ),
    )


class BooleanAnnotation(BaseAnnotation):
    """
    An annotation is a way of tagging the content with a label of some kind.

    This class will probably be broken up in the future, but covers most of our
    initial cases.
    """

    annotation_type: Literal[AnnotationType.BOOLEAN] = AnnotationType.BOOLEAN
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
    annotations: list[Annotation] = Field(min_length=1)


class DriverVersion(StrEnum):
    """
    The version based on the DRIVER guidelines versioning scheme.

    (Borrowed from OpenAlex)
    """

    PUBLISHED_VERSION = "publishedVersion"
    """The document's version of record. This is the most authoritative version."""
    ACCEPTED_VERSION = "acceptedVersion"
    """
    The document after having completed peer review and being officially accepted for
    publication. It will lack publisher formatting, but the content should be
    interchangeable with that of the publishedVersion.
    """
    SUBMITTED_VERSION = "submittedVersion"
    """
    The document as submitted to the publisher by the authors, but before peer-review.
    Its content may differ significantly from that of the accepted article."""
    OTHER = "other"
    """Other version."""


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
        min_length=1,
        description="A list of locations where this reference can be found.",
    )


class ReferenceAssociationType(StrEnum):
    """
    The type of association between references.

    Direction is important: "this reference <association_type> associated reference".
    """

    CITES = auto()
    """This reference cites the related reference."""
    IS_CITED_BY = auto()
    """This reference is cited by the related reference."""
    IS_SIMILAR_TO = auto()
    """This reference is similar to the related reference."""


class ReferenceAssociationEnhancement(BaseModel):
    """An enhancement for storing associations between references."""

    enhancement_type: Literal[EnhancementType.REFERENCE_ASSOCIATION] = (
        EnhancementType.REFERENCE_ASSOCIATION
    )
    associated_reference_ids: list[Identifier] = Field(
        min_length=1,
        description=(
            "A list of Identifiers which are associated to this reference. "
            "These can either be ExternalIdentifiers or resolved repository UUID4s."
        ),
    )
    association_type: ReferenceAssociationType = Field(
        description=(
            "The type of association between this reference and the associated ones. "
            "Direction is important: "
            '"this reference <association_type> associated reference".'
        )
    )


class RawEnhancement(BaseModel):
    """
    An enhancement for storing raw/arbitrary/unstructured data.

    Data in these enhancements is intended for future conversion into structured form.

    This enhancement accepts any fields passed in to `data`. These enhancements cannot
    be created by robots.
    """

    enhancement_type: Literal[EnhancementType.RAW] = EnhancementType.RAW
    source_export_date: datetime.datetime = Field(
        description="Date the enhancement data was retrieved."
    )
    description: str = Field(
        description="Description of the data to aid in future refinement."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata to aid in future structuring of raw data",
    )
    data: Any = Field(description="Unstructured data for later processing.")

    @model_validator(mode="after")
    def forbid_no_data(self) -> Self:
        """Prevent a raw enhancement from being created with no data."""
        if not self.data:
            msg = "data must be populated on a raw enhancement."
            raise ValueError(msg)
        return self

    @property
    def fingerprint(self) -> str:
        """
        The unique fingerprint of this raw enhancement.

        Excludes the source_export_date from the fingerprint calculation, meaning
        that two raw enhancements with identical data but different export dates
        will be considered the same.

        Unstructured data in `data` and `metadata` is included in the fingerprint,
        sorted by key.
        """
        return json.dumps(
            self.model_dump(
                mode="json", exclude={"source_export_date"}, exclude_none=True
            ),
            sort_keys=True,
        )


#: Union type for all enhancement content types.
EnhancementContent = Annotated[
    BibliographicMetadataEnhancement
    | AbstractContentEnhancement
    | AnnotationEnhancement
    | LocationEnhancement
    | ReferenceAssociationEnhancement
    | RawEnhancement,
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
