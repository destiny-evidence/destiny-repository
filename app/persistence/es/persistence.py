"""Objects used to interface with SQL implementations."""

from abc import abstractmethod
from typing import Generic, Literal, Self, get_args, get_origin
from uuid import UUID

from elasticsearch.dsl import AsyncDocument, InnerDoc
from elasticsearch.dsl.document_base import InstrumentedField
from elasticsearch.dsl.field import Nested
from elasticsearch.dsl.response import Hit
from elasticsearch.dsl.utils import AttrList
from pydantic import UUID4, BaseModel, Field

from app.domain.base import (
    SQLAttributeMixin,  # noqa: F401, required for Pydantic generic construction
)
from app.persistence.generics import GenericDomainModelType


# NB does not inherit ABC due to metadata mixing issues.
# https://stackoverflow.com/a/49668970
class GenericESPersistence(
    AsyncDocument,
    Generic[GenericDomainModelType],
):
    """
    Generic implementation for an elasticsearch persistence model.

    At a minimum, the `from_domain` and `to_domain` methods should be implemented.
    """

    __abstract__ = True

    @classmethod
    @abstractmethod
    def from_domain(cls, domain_obj: GenericDomainModelType) -> Self:
        """Create a persistence model from a domain model."""

    @abstractmethod
    def to_domain(self) -> GenericDomainModelType:
        """Create a domain model from this persistence model."""

    @classmethod
    def from_hit(cls, hit: Hit) -> Self:
        """Create a persistence model from an Elasticsearch Hit object."""
        return cls(
            **nested_hit_to_document(hit.to_dict(), cls),
            meta={"id": hit.meta.id},
        )

    class Index:
        """
        Index metadata for the persistence model.

        Implementer must define this subclass.
        """

        name: str


class GenericNestedDocument(InnerDoc):
    """Generic implementation for an elasticsearch nested document."""

    @classmethod
    def from_hit(cls, hits: dict) -> Self:
        """Create a persistence model from an Elasticsearch Hit dict."""
        return cls(**nested_hit_to_document(hits, cls))


def nested_hit_to_document(  # noqa: PLR0912
    data: dict, cls: type[GenericESPersistence] | type[GenericNestedDocument]
) -> dict:
    """
    Flatten a nested hit dictionary from Elasticsearch.

    This function converts any nested values in the input dict into NestedDocument
    instances. It is called recursively to eventually return a flat dictionary
    of the root Elasticsearch document.

    Despite the fact it would seem that Elasticsearch DSL should return Documents,
    it actually returns Hit objects, which need to be converted.

    See Also:
    - https://discuss.elastic.co/t/elasticsearch-python-client-search-does-not-return-documents/315066
    - https://stackoverflow.com/questions/54460329/how-to-convert-a-hit-into-a-document-with-elasticsearch-dsl.

    The built-in .from_es() is only useful for simple flat documents and doesn't
    play nice with our nested fields and mixins.

    """
    # Collect all annotations from the class and its parents (including mixins)
    all_annotations = {}
    for base in reversed(cls.__mro__):
        if hasattr(base, "__annotations__"):
            all_annotations.update(base.__annotations__)

    for key, value in data.items():
        field = getattr(cls, key, None)
        if not field:
            msg = f"Field '{key}' not found in {cls.__name__}"
            raise ValueError(msg)
        if not isinstance(field, InstrumentedField):
            msg = f"Field '{key}' in {cls.__name__} is not a valid Elasticsearch field"
            raise TypeError(msg)
        field_mapping = field._field  # noqa: SLF001
        if isinstance(
            field_mapping,
            Nested,
        ):
            doc_class = field_mapping._doc_class  # noqa: SLF001
            if not issubclass(doc_class, GenericNestedDocument):
                msg = (
                    f"Nested field '{key}' in {cls.__name__} does not inherit "
                    "GenericNestedDocument"
                )
                raise TypeError(msg)
            data[key] = [doc_class.from_hit(item) for item in value]

        # Sometimes Elasticsearch returns single-item lists for non-list fields...
        # This checks the type hint on the persistence class to see if it's a list type,
        # and unwraps it if not.
        # We've only seen this behavior on test data so far, but this is a safeguard.
        if isinstance(value, list | AttrList) and all_annotations.get(key):
            is_list_type = False
            if get_origin(all_annotations.get(key)) is list:
                is_list_type = True
            for arg in get_args(all_annotations.get(key)):
                if get_origin(arg) is list:
                    is_list_type = True
            if not is_list_type:
                if len(value) > 1:
                    msg = (
                        f"Cannot unwrap returned list field '{key}' "
                        "with multiple values"
                    )
                    raise ValueError(msg)
                data[key] = value[0] if value else None

    return data


class ESScoreResult(BaseModel):
    """Simple class for id<->score mapping in Elasticsearch search results."""

    id: UUID4
    score: float


class ESSearchTotal(BaseModel):
    """
    Class for total results in Elasticsearch search results.

    Unless otherwise specified in the request, Elasticsearch will stop counting after
    10,000 and return a lower bound with relation "gte".
    """

    value: int = Field(description="The total number of results found.")
    relation: Literal["eq", "gte"] = Field(
        description=(
            "Indicates whether the total count is exact or just a lower bound."
        ),
    )


class ESSearchResult(BaseModel, Generic[GenericDomainModelType]):
    """Wrapping class for Elasticsearch search results."""

    hits: list[UUID] = Field(
        default_factory=list,
        description="The list of object IDs returned from the search query.",
    )
    total: ESSearchTotal = Field(
        description="The total number of results matching the search query.",
    )
    page: int = Field(
        description="The page number of the results.",
    )
