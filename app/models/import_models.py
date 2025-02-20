"""Models associated with an import batch file."""

from abc import ABC
from enum import Enum, StrEnum, auto
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, PastDate


class OtherIdentifier(BaseModel):
    """
    Any other identifier not defined.

    This should be used sparingly.
    """

    identifier_type: Literal["other"]
    other_identifier_name: Annotated[
        str,
        Field(
            ...,
            description="""
The name of the undocumented identifier type. This should be consistent to allow
later consolidation into a documented identifier type.
""",
        ),
    ]
    identifier: Annotated[str, Field(description="The value of the identifier.")]


class DoiIdentifier(BaseModel):
    """Represents a DOI for the purposes of identifying a reference."""

    identifier_type: Literal["doi"]
    identifier: Annotated[
        HttpUrl, Field(description="The DOI which identifies a reference")
    ]


class PubMedIdentifier(BaseModel):
    """Represents pmid from PubMed."""

    identifier_type: Literal["pmid"]
    identifier: Annotated[
        int, Field(description="The pmid which identifies a reference")
    ]


class OpenAlexIdentifier(BaseModel):
    """Represents an external identifier specific to OpenAlex."""

    identifier_type: Literal["openalex"]
    identifier: Annotated[
        str,
        Field(
            ..., pattern=r"^W\d+", description="The OpenAlex work id of the reference"
        ),
    ]


ExternalIdentifier = Annotated[
    OpenAlexIdentifier | DoiIdentifier | PubMedIdentifier | OtherIdentifier,
    Field(discriminator="identifier_type"),
]


class Visibility(StrEnum):
    """
    The visibility of a data element in the repository.

    This is used to manage whether information should be publicly available or
    restricted (generally due to copyright constriants from publishers.)

    **Allowed values**:

    - `public`: Visible to the general public without authentication.
    - `restricted`: Requires authentication to be visble.
    - `hidden`: Is not visible, but may be passed to data mining processes.
    """

    public = auto()
    restricted = auto()
    hidden = auto()


class EnhancementBase(BaseModel, ABC):
    """
    Base class for enhancements.

    An enhancement is any data about a reference which is in addition to the
    identifiers of that reference. Anything which is useful is generally an
    enhancement. They will be flattened and composed for search and access.

    This class should not be used directly, but inherited from to define new
    enhancement classes.
    """

    enhancement_type: Annotated[
        str,
        Field(
            ..., description="The discriminator for the type of enhancement this is."
        ),
    ]
    source: Annotated[
        str,
        Field(
            ...,
            description="The enhancement source for tracking provencance.",
        ),
    ]
    visibility: Annotated[
        Visibility, Field(..., description="The level of visibility of the enhancement")
    ]


class AuthorPostion(str, Enum):
    """
    The position of an author in a list of authorships.

    Maps to the data from OpenAlex.

    **Allowed values**:
    - `first`: The first author.
    - `middle`: Any middle author
    - `last`: The last author
    """

    first = "first"
    middle = "middle"
    last = "last"


class Authorship(BaseModel):
    """
    Represents a single author and their association with a reference.

    This is a simplification of the OpenAlex [Authorship
    object](https://docs.openalex.org/api-entities/works/work-object/authorship-object)
    for our purposes.
    """

    display_name: Annotated[
        str, Field(..., description="The display name of the author.")
    ]
    orcid: Annotated[str, Field(..., description="The ORCid of the author.")]
    position: Annotated[
        AuthorPostion,
        Field(
            ..., description="The position of the author within the list of authors."
        ),
    ]


class BibliographicMetadata(EnhancementBase):
    """
    An enhancement which is made up of bibliographic metadata.

    Generally this will be sourced from a database such as OpenAlex or similar.
    For directly contributed references, these may not be complete.
    """

    enhancement_type: Literal["bibliographic"]
    visibility: Annotated[Visibility, Field(Visibility.public)]
    authorship: Annotated[
        list[Authorship] | None,
        Field(
            None,
            description="A list of `Authorships` belonging to this reference.",
        ),
    ] = None
    cited_by_count: Annotated[
        int | None,
        Field(
            None,
            description="""
(From OpenAlex)The number of citations to this work. These are the times that
other works have cited this work
""",
        ),
    ]
    created_date: Annotated[
        PastDate | None,
        Field(None, description="The ISO8601 date this metadata record was created"),
    ]
    publication_date: Annotated[
        PastDate | None,
        Field(None, description="The date which the version of record was published."),
    ]
    publication_year: Annotated[
        int | None,
        Field(
            None, description="The year in which the version of record was published."
        ),
    ]
    publisher: Annotated[
        str | None,
        Field(
            None,
            description="The name of the entity which published the version of record.",
        ),
    ]


class AbstractContentEnhancement(EnhancementBase):
    """
    An enhancement which is specific to the abstract of a reference.

    This is separate from the `BibliographicMetadata` for two reasons:

    1. Abstracts are increasingly missing from sources like OpenAlex, and may be
    backfilled from other sources, without the bibliographic metadata.
    2. They are also subject to copyright limitations in ways which metadata are
    not, and thus need separate visibility controls.
    """

    enhancement_type: Literal["abstract"]
    process: Literal["uninverted", "closed_api", "other"]
    abstract: str = Field(..., description="The abstract of the reference.")


class Annotation(BaseModel):
    """
    An annotation is a way of tagging the content with a label of some kind.

    This class will probably be broken up in the future, but covers most of our
    initial cases.
    """

    annotation_type: str = Field(
        ...,
        description="An identifier for the type of annotation",
        examples=["openalex:topic", "pubmed:mesh"],
    )
    label: str = Field(
        ...,
        description="A high level label for this annotation like the name of the topic",
    )
    data: dict = Field(
        ...,
        description="""
An object representation of the annotation including any confidence scores or
descriptions.
""",
    )


class AnnotationsEnhancement(EnhancementBase):
    """An enhancement which is composed of a list of Annotations."""

    enhancement_type: Literal["annotations"]
    source: str
    visibility: Visibility
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


class Location(BaseModel):
    """
    A location where a reference can be found.

    This maps almost completely to the OpenAlex
    [Location object](https://docs.openalex.org/api-entities/works/work-object/location-object)
    """

    is_oa: Annotated[
        bool | None,
        Field(
            None,
            description="""
(From OpenAlex): True if an Open Access (OA) version of this work is available
at this location. May be left as null if this is unknown (and thus)
treated effectively as `false`.
""",
        ),
    ]
    version: Annotated[
        DriverVersion | None,
        Field(
            None,
            description="""
The version (according to the DRIVER versioning scheme) of this location.
""",
        ),
    ]
    landing_page_url: Annotated[
        HttpUrl | None,
        Field(
            None, description="(From OpenAlex): The landing page URL for this location."
        ),
    ]
    pdf_url: Annotated[
        HttpUrl | None,
        Field(
            None,
            description="""
(From OpenAlex): A URL where you can find this location as a PDF.
""",
        ),
    ]
    license: Annotated[
        str | None,
        Field(
            None,
            description="""
(From OpenAlex): The location's publishing license. This can be a Creative
Commons license such as cc0 or cc-by, a publisher-specific license, or null
which means we are not able to determine a license for this location.
""",
        ),
    ]
    extra: Annotated[
        dict | None, Field(None, description="Any extra metadata about this location")
    ]


class LocationsEnhancement(EnhancementBase):
    """
    An enhancement which describes locations where this reference can be found.

    This maps closely (almost exactly) to OpenAlex's locations.
    """

    enhancement_type: Literal["locations"]
    locations: Annotated[
        list[Location],
        Field(description="A list of locations where this reference can be found."),
    ]


Enhancement = Annotated[
    BibliographicMetadata
    | AbstractContentEnhancement
    | AnnotationsEnhancement
    | LocationsEnhancement,
    Field(discriminator="enhancement_type"),
]


class EnhancedReference(BaseModel):
    """
    A record which encapsulates a reference to be imported.

    This should include at least one identifier and one enhancement (otherwise
    it's not very useful).
    """

    identifiers: Annotated[
        list[ExternalIdentifier],
        Field(
            ...,
            min_length=1,
            description="A list of `ExternalIdentifiers` for the Reference",
        ),
    ]
    enhancements: Annotated[
        list[Enhancement],
        Field(
            ..., min_length=1, description="A list of enhancements for the reference"
        ),
    ]
