"""Objects used to interface with SQL implementations."""

from abc import abstractmethod
from typing import Generic, Self

from elasticsearch.dsl import AsyncDocument, InnerDoc
from elasticsearch.dsl.document_base import InstrumentedField
from elasticsearch.dsl.field import Nested
from elasticsearch.dsl.response import Hit
from pydantic import UUID4, BaseModel

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


def nested_hit_to_document(
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
    for key, value in data.items():
        field = getattr(cls, key, None)
        if not field:
            msg = f"Field '{key}' not found in {cls.__name__}"
            raise ValueError(msg)
        if not isinstance(field, InstrumentedField):
            msg = f"Field '{key}' in {cls.__name__} is not a valid Elasticsearch field"
            raise TypeError(msg)
        nested_field = field._field  # noqa: SLF001
        if isinstance(
            nested_field,
            Nested,
        ):
            doc_class = nested_field._doc_class  # noqa: SLF001
            if not issubclass(doc_class, GenericNestedDocument):
                msg = (
                    f"Nested field '{key}' in {cls.__name__} does not inherit "
                    "GenericNestedDocument"
                )
                raise TypeError(msg)
            data[key] = [doc_class.from_hit(item) for item in value]
    return data


class ESSearchResult(BaseModel):
    """Simple class for id<->score mapping in Elasticsearch search results."""

    id: UUID4
    score: float
