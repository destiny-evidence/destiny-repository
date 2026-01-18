"""Tests for deduplication scoring utilities and scorer."""

from uuid import UUID, uuid4

import pytest

from app.core.config import DedupScoringConfig
from app.domain.references.deduplication.scoring import (
    ConfidenceLevel,
    PairScorer,
    ReferenceDeduplicationView,
)
from app.domain.references.deduplication.scoring.utils import (
    title_token_jaccard,
    tokenize,
)


def _es_scores(*views: ReferenceDeduplicationView) -> dict[UUID, float]:
    """Helper to create type-safe es_scores dict from views with known IDs."""
    return {v.id: 0.0 for v in views if v.id is not None}


class TestTokenize:
    """Tests for the tokenize utility function."""

    def test_tokenize_simple(self):
        """Basic tokenization extracts alphanumeric words."""
        assert tokenize("Hello World") == ["hello", "world"]

    def test_tokenize_with_punctuation(self):
        """Punctuation is stripped during tokenization."""
        assert tokenize("Hello, World!") == ["hello", "world"]
        assert tokenize("Einleitung.") == ["einleitung"]

    def test_tokenize_preserves_numbers(self):
        """Numbers are preserved as tokens."""
        assert tokenize("Chapter 3: Introduction") == ["chapter", "3", "introduction"]

    def test_tokenize_empty_input(self):
        """Empty or None input returns empty list."""
        assert tokenize("") == []
        assert tokenize(None) == []

    def test_tokenize_only_punctuation(self):
        """String with only punctuation returns empty list."""
        assert tokenize("...") == []
        assert tokenize("!@#$%") == []

    def test_tokenize_case_insensitive(self):
        """Tokens are lowercased."""
        assert tokenize("HELLO World") == ["hello", "world"]

    # XML/HTML/MathML tag stripping tests
    def test_tokenize_strips_simple_html_tags(self):
        """HTML tags are stripped during tokenization."""
        assert tokenize("<b>Bold</b> text") == ["bold", "text"]
        assert tokenize("<i>italic</i>") == ["italic"]

    def test_tokenize_strips_self_closing_tags(self):
        """Self-closing tags are stripped."""
        assert tokenize("Line<br/>break") == ["line", "break"]
        assert tokenize("Image<img src='test.png'/>here") == ["image", "here"]

    def test_tokenize_strips_mathml_tags(self):
        """MathML tags with namespaces are stripped.

        This prevents false positive matches on common MathML tokens like
        'mml', 'math', 'xmlns' that appear in scientific paper titles.
        """
        # Example from PubMed titles with MathML
        result = tokenize(
            '<mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML">x</mml:math>'
        )
        assert result == ["x"]
        assert "mml" not in result
        assert "math" not in result
        assert "xmlns" not in result

    def test_tokenize_strips_scp_tags(self):
        """PubMed scp (small caps) tags are stripped.

        These appear in titles like "UCSF <scp>ChimeraX</scp>: Meeting
        modern challenges".
        """
        assert tokenize("UCSF <scp>ChimeraX</scp>") == ["ucsf", "chimerax"]

    def test_tokenize_strips_nested_tags(self):
        """Nested tags are properly stripped."""
        assert tokenize("<div><span>nested</span> content</div>") == [
            "nested",
            "content",
        ]

    def test_tokenize_preserves_content_between_tags(self):
        """Content between tags is preserved."""
        result = tokenize("The <i>quick</i> brown <b>fox</b>")
        assert result == ["the", "quick", "brown", "fox"]

    def test_tokenize_complex_mathml_expression(self):
        """Complex MathML expressions are handled correctly."""
        # Simulating a title like "Effects of CO<sub>2</sub> on climate"
        result = tokenize("Effects of CO<sub>2</sub> on climate")
        assert result == ["effects", "of", "co", "2", "on", "climate"]

    def test_tokenize_mixed_tags_and_text(self):
        """Mixed content with various tag types works correctly."""
        title = '<mml:mi mathvariant="normal">CO</mml:mi><sub>2</sub> emissions'
        result = tokenize(title)
        assert "co" in result
        assert "2" in result
        assert "emissions" in result
        # MathML attribute content should NOT be included
        assert "mathvariant" not in result
        assert "normal" not in result


class TestTitleTokenJaccard:
    """Tests for the title_token_jaccard function."""

    def test_identical_titles(self):
        """Identical titles have Jaccard similarity of 1.0."""
        assert title_token_jaccard("Hello World", "Hello World") == 1.0

    def test_identical_with_punctuation(self):
        """Titles that differ only in punctuation have similarity 1.0."""
        assert title_token_jaccard("Einleitung.", "Einleitung") == 1.0
        assert title_token_jaccard("Hello, World!", "Hello World") == 1.0

    def test_partial_overlap(self):
        """Partial overlap yields expected Jaccard score."""
        # {hello} & {hello, world} = {hello}, union = {hello, world}
        assert title_token_jaccard("Hello", "Hello World") == 0.5

    def test_no_overlap(self):
        """No overlap yields Jaccard of 0.0."""
        assert title_token_jaccard("Hello", "Goodbye") == 0.0

    def test_empty_input(self):
        """Empty or None input yields 0.0."""
        assert title_token_jaccard("", "Hello") == 0.0
        assert title_token_jaccard("Hello", "") == 0.0
        assert title_token_jaccard(None, "Hello") == 0.0
        assert title_token_jaccard("Hello", None) == 0.0
        assert title_token_jaccard(None, None) == 0.0

    def test_case_insensitive(self):
        """Jaccard is case-insensitive."""
        assert title_token_jaccard("Hello World", "HELLO WORLD") == 1.0


class TestReferenceDeduplicationView:
    """Tests for ReferenceDeduplicationView."""

    def test_from_dict(self):
        """Can create view from dictionary."""
        view = ReferenceDeduplicationView(
            id=uuid4(),
            title="Test Title",
            authors=["Author One", "Author Two"],
            publication_year=2024,
            doi="10.1234/test",
            openalex_id="W123456",
            pmid="12345678",
        )
        assert view.title == "Test Title"
        assert view.doi == "10.1234/test"
        assert view.openalex_id == "W123456"


class TestPairScorer:
    """Tests for the PairScorer class."""

    @pytest.fixture
    def config(self) -> DedupScoringConfig:
        """Default scoring config for tests."""
        return DedupScoringConfig()

    @pytest.fixture
    def scorer(self, config: DedupScoringConfig) -> PairScorer:
        """Create a scorer with default config."""
        return PairScorer(config)

    def test_openalex_id_match(self, scorer: PairScorer):
        """OpenAlex ID match yields HIGH confidence."""
        cand_id = uuid4()
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="Test Title",
            openalex_id="W123456",
        )
        candidate = ReferenceDeduplicationView(
            id=cand_id,
            title="Different Title",
            openalex_id="W123456",
        )
        es_scores: dict[UUID, float] = {cand_id: 50.0}

        results = scorer.score_source_two_stage(source, [candidate], es_scores)
        assert len(results) == 1
        _, result = results[0]
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.id_match_type == "openalex"
        assert result.combined_score == 1.0

    def test_doi_match_with_safety_gate(self, scorer: PairScorer):
        """DOI match with corroborating evidence yields HIGH confidence."""
        cand_id = uuid4()
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="A Very Long Title With Many Words For Safety",
            publication_year=2024,
            doi="10.1234/test",
        )
        candidate = ReferenceDeduplicationView(
            id=cand_id,
            title="Different Title",
            doi="10.1234/test",
        )
        es_scores: dict[UUID, float] = {cand_id: 50.0}

        results = scorer.score_source_two_stage(source, [candidate], es_scores)
        _, result = results[0]
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.id_match_type == "doi_safe"

    def test_doi_match_without_safety_gate(self, scorer: PairScorer):
        """DOI match without corroborating evidence falls through to ES scoring."""
        cand_id = uuid4()
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="Short",  # Only 1 token, no year
            doi="10.1234/test",
        )
        candidate = ReferenceDeduplicationView(
            id=cand_id,
            title="Different",
            doi="10.1234/test",
        )
        es_scores: dict[UUID, float] = {cand_id: 30.0}

        results = scorer.score_source_two_stage(source, [candidate], es_scores)
        _, result = results[0]
        # Should NOT get HIGH confidence due to missing safety gate
        assert result.confidence == ConfidenceLevel.LOW
        assert result.id_match_type is None

    def test_high_es_score(self, scorer: PairScorer):
        """ES score >= 100 with good Jaccard yields HIGH confidence."""
        cand_id = uuid4()
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="Test Title",
        )
        candidate = ReferenceDeduplicationView(
            id=cand_id,
            title="Test Title",
        )
        es_scores: dict[UUID, float] = {cand_id: 120.0}

        results = scorer.score_source_two_stage(source, [candidate], es_scores)
        _, result = results[0]
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.es_score == 120.0

    def test_high_es_score_low_jaccard_rejected(self, scorer: PairScorer):
        """ES score >= 100 but low Jaccard should NOT yield HIGH confidence.

        This prevents false positives from papers with large author lists
        (e.g., CERN papers with 2900+ authors) where single-letter initials
        inflate ES scores despite completely different titles.
        """
        cand_id = uuid4()
        # ATLAS paper title (physics)
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="A continuous calibration of the ATLAS flavour-tagging "
            "classifiers via optimal transportation maps",
        )
        # Sausage paper title (food science) - completely unrelated
        candidate = ReferenceDeduplicationView(
            id=cand_id,
            title="Modeling the growth of natural microbiota in Frankfurt-type "
            "sausages for predictive shelf-life validation: a case study",
        )
        # High ES score (could happen due to author initial matching)
        es_scores: dict[UUID, float] = {cand_id: 2780.0}

        results = scorer.score_source_two_stage(source, [candidate], es_scores)
        _, result = results[0]
        # Should NOT be HIGH confidence due to low Jaccard (~0.1)
        assert result.confidence == ConfidenceLevel.LOW
        assert result.jaccard_score is not None
        assert result.jaccard_score < 0.3

    def test_medium_es_with_jaccard(self, scorer: PairScorer):
        """ES score 50-100 with good Jaccard yields MEDIUM confidence."""
        cand_id = uuid4()
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="Climate change impacts on health",
        )
        candidate = ReferenceDeduplicationView(
            id=cand_id,
            title="Climate change impacts on public health",
        )
        es_scores: dict[UUID, float] = {cand_id: 75.0}

        results = scorer.score_source_two_stage(source, [candidate], es_scores)
        _, result = results[0]
        assert result.confidence == ConfidenceLevel.MEDIUM
        assert result.jaccard_score is not None
        assert result.jaccard_score >= 0.6

    def test_low_es_score(self, scorer: PairScorer):
        """ES score < 50 yields LOW confidence."""
        cand_id = uuid4()
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="Test Title",
        )
        candidate = ReferenceDeduplicationView(
            id=cand_id,
            title="Completely Different Title",
        )
        es_scores: dict[UUID, float] = {cand_id: 30.0}

        results = scorer.score_source_two_stage(source, [candidate], es_scores)
        _, result = results[0]
        assert result.confidence == ConfidenceLevel.LOW

    def test_short_title_fallback(self, scorer: PairScorer):
        """Short titles with ES >= 20 and perfect Jaccard yield MEDIUM."""
        cand_id = uuid4()
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="Einleitung",  # Single word
        )
        candidate = ReferenceDeduplicationView(
            id=cand_id,
            title="Einleitung",  # Exact match
        )
        es_scores: dict[UUID, float] = {cand_id: 25.0}

        results = scorer.score_source_two_stage(source, [candidate], es_scores)
        _, result = results[0]
        assert result.confidence == ConfidenceLevel.MEDIUM
        assert result.jaccard_score is not None
        assert result.jaccard_score >= 0.99

    def test_multiple_candidates_sorted_by_score(self, scorer: PairScorer):
        """Multiple candidates are returned sorted by combined score."""
        cand1_id, cand2_id = uuid4(), uuid4()
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="Test Title",
            openalex_id="W123",
        )
        cand1 = ReferenceDeduplicationView(
            id=cand1_id,
            title="Different",
        )
        cand2 = ReferenceDeduplicationView(
            id=cand2_id,
            title="Test Title",
            openalex_id="W123",  # Matches source
        )
        es_scores: dict[UUID, float] = {cand1_id: 80.0, cand2_id: 50.0}

        results = scorer.score_source_two_stage(source, [cand1, cand2], es_scores)
        assert len(results) == 2
        # cand2 should be first (OpenAlex match = 1.0 score)
        assert results[0][0].id == cand2_id
        assert results[0][1].combined_score > results[1][1].combined_score

    def test_empty_candidates(self, scorer: PairScorer):
        """Empty candidates list returns empty results."""
        source = ReferenceDeduplicationView(
            id=uuid4(),
            title="Test Title",
        )
        results = scorer.score_source_two_stage(source, [], {})
        assert results == []
