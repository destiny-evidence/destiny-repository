"""Unit test for Lucene query string escaping in annotation filters."""

from app.domain.references.models.models import AnnotationFilter
from app.domain.references.services.search_service import SearchService


class _StubSearchService(SearchService):
    """SearchService without dependencies, for testing filter builders."""

    def __init__(self) -> None:
        pass


def test_annotation_filter_escapes_quotes_in_label():
    """Quotes in label must not break out of the quoted annotation term."""
    # Without fix: annotations:"test/unescaped"quote"
    #   — the " terminates the quoted term early, leaving `quote"` as
    #     bare Lucene syntax that can alter query logic.
    service = _StubSearchService()
    result = service._build_annotation_query_string_filter(  # noqa: SLF001
        AnnotationFilter(scheme="test", label='unescaped"quote'),
    )
    assert result == r'annotations:"test/unescaped\"quote"'
