import threading
from importlib.metadata import version

import pytest
from destiny_deduper import FieldResult as DeduperFieldResult
from destiny_deduper import FieldStatus, PairLabel, PairScoreResult, get_library_info
from destiny_deduper.logger import logger as deduper_logger
from destiny_sdk.enhancements import AuthorPosition, Authorship
from destiny_sdk.identifiers import DOIIdentifier
from pydantic import ValidationError

from app.domain.references.models.models import (
    DeduplicationFieldStatus,
    DeduplicationPaper,
)
from app.domain.references.services import deduper_pair_scorer
from app.domain.references.services.deduper_pair_scorer import DeduperPairScorer

TITLE = "Adolescent vaccination uptake in low-income settings"
DOI = DOIIdentifier(identifier="10.1234/abc.123")


def _authors(*names: str) -> list[Authorship]:
    return [
        Authorship(display_name=name, position=AuthorPosition.FIRST) for name in names
    ]


def _paper(**overrides) -> DeduplicationPaper:
    return DeduplicationPaper(
        **{
            "title": TITLE,
            "authors": _authors("Ada Lovelace", "Grace Hopper"),
            "year": 2019,
            "journal": "Journal of Bone Research",
            **overrides,
        }
    )


def test_metadata_reports_the_installed_deduper():
    library_info = get_library_info()

    metadata = DeduperPairScorer().metadata

    assert metadata.package_version == version("destiny-deduper")
    assert metadata.configuration_hash == library_info.config_hash
    assert metadata.threshold == library_info.decision_threshold
    assert (
        metadata.effective_configuration["weights"]
        == (library_info.scoring_config["weights"])
    )


@pytest.mark.asyncio
async def test_scores_a_matching_pair():
    # DOI makes this abbreviation match clear the threshold.
    result = await DeduperPairScorer().score_pair(
        incoming=_paper(doi=DOI), candidate=_paper(doi=DOI, journal="J Bone Res")
    )

    assert result.probability is not None
    assert result.unscorable_reason is None
    assert result.early_stop_reason is None
    assert result.suggested_label == PairLabel.DUPLICATE
    title = result.field_comparisons["title"]
    assert title.status == DeduplicationFieldStatus.COMPARED
    assert title.incoming_value == TITLE
    assert title.candidate_value == TITLE
    assert title.score == 1.0
    # Normalised values explain the score separately from the raw values.
    authors = result.field_comparisons["authors"]
    assert authors.normalised_incoming_value == "Ada Lovelace, Grace Hopper"
    assert authors.normalised_candidate_value == "Ada Lovelace, Grace Hopper"


@pytest.mark.asyncio
async def test_reports_object_valued_fields_as_structured_values():
    result = await DeduperPairScorer().score_pair(
        incoming=_paper(doi=DOI), candidate=_paper(doi=DOI)
    )

    assert result.field_comparisons["doi"].incoming_value == {
        "identifier": "10.1234/abc.123",
        "identifier_type": "doi",
    }
    # Only display names reach the comparator.
    assert result.field_comparisons["authors"].incoming_value == [
        "Ada Lovelace",
        "Grace Hopper",
    ]


@pytest.mark.asyncio
async def test_reports_no_authors_as_absent_rather_than_an_empty_list():
    result = await DeduperPairScorer().score_pair(
        incoming=_paper(authors=None), candidate=_paper()
    )

    authors = result.field_comparisons["authors"]
    assert authors.status == DeduplicationFieldStatus.MISSING_INCOMING
    assert authors.incoming_value is None
    assert authors.candidate_value == ["Ada Lovelace", "Grace Hopper"]


@pytest.mark.asyncio
async def test_keeps_the_deduper_value_for_a_field_no_paper_carries(monkeypatch):
    scored = PairScoreResult(
        probability=0.5,
        doi_mismatch_adjustment_applied=False,
        field_results={
            "publisher": DeduperFieldResult(
                status=FieldStatus.MISSING_A, value_b="Elsevier"
            )
        },
        label=PairLabel.NOT_DUPLICATE,
    )
    monkeypatch.setattr(
        deduper_pair_scorer.Deduper, "score_pair", lambda *_a, **_kw: scored
    )

    result = await DeduperPairScorer().score_pair(incoming=_paper(), candidate=_paper())

    assert result.field_comparisons["publisher"].candidate_value == "Elsevier"


@pytest.mark.asyncio
async def test_scoring_emits_no_library_log_records():
    # Loguru binds stderr at import, so assert on the library logger.
    records = []
    sink_id = deduper_logger.add(records.append, level="DEBUG")
    try:
        await DeduperPairScorer().score_pair(incoming=_paper(), candidate=_paper())
    finally:
        deduper_logger.remove(sink_id)

    assert records == []


@pytest.mark.asyncio
async def test_reports_that_the_doi_mismatch_penalty_was_applied():
    result = await DeduperPairScorer().score_pair(
        incoming=_paper(doi=DOI),
        candidate=_paper(doi=DOIIdentifier(identifier="10.9999/zzz.999")),
    )

    assert result.doi_mismatch_adjusted is True
    assert result.probability is not None
    assert result.field_comparisons["doi"].score is not None


@pytest.mark.asyncio
async def test_reports_that_no_doi_mismatch_penalty_was_applied():
    result = await DeduperPairScorer().score_pair(
        incoming=_paper(doi=DOI), candidate=_paper(doi=DOI)
    )

    assert result.doi_mismatch_adjusted is False


@pytest.mark.asyncio
async def test_reports_which_side_a_field_was_absent_from():
    result = await DeduperPairScorer().score_pair(
        incoming=_paper(pages="10-20"), candidate=_paper(issue="3")
    )

    assert result.field_comparisons["pages"].status == (
        DeduplicationFieldStatus.MISSING_CANDIDATE
    )
    assert result.field_comparisons["pages"].incoming_value == "10-20"
    assert result.field_comparisons["issue"].status == (
        DeduplicationFieldStatus.MISSING_INCOMING
    )
    assert result.field_comparisons["issue"].candidate_value == "3"
    assert result.field_comparisons["doi"].status == (
        DeduplicationFieldStatus.MISSING_BOTH
    )
    assert result.probability is not None


@pytest.mark.asyncio
async def test_carries_the_early_stop_reason():
    result = await DeduperPairScorer().score_pair(
        incoming=_paper(),
        candidate=_paper(title="Coastal erosion under sea level rise"),
    )

    assert result.early_stop_reason is not None
    assert result.probability == 0.0
    assert result.field_comparisons == {}
    assert result.suggested_label == PairLabel.NOT_DUPLICATE


@pytest.mark.asyncio
async def test_reports_an_unscorable_pair_without_a_probability(monkeypatch):
    unscorable = PairScoreResult(
        probability=0.0,
        doi_mismatch_adjustment_applied=False,
        field_results={
            "title": DeduperFieldResult(status=FieldStatus.MISSING_A, value_b=TITLE),
            "year": DeduperFieldResult(status=FieldStatus.MISSING_B, value_a="2019"),
        },
        label=PairLabel.UNSCORABLE,
        unscorable_reason="no_comparable_fields",
    )
    monkeypatch.setattr(
        deduper_pair_scorer.Deduper, "score_pair", lambda *_args, **_kwargs: unscorable
    )

    result = await DeduperPairScorer().score_pair(
        incoming=_paper(title=None), candidate=_paper(year=None)
    )

    assert result.probability is None
    assert result.unscorable_reason == "no_comparable_fields"
    title = result.field_comparisons["title"]
    assert title.status == DeduplicationFieldStatus.MISSING_INCOMING
    assert title.incoming_value is None
    assert title.candidate_value == TITLE
    year = result.field_comparisons["year"]
    assert year.status == DeduplicationFieldStatus.MISSING_CANDIDATE
    assert year.candidate_value is None


@pytest.mark.asyncio
async def test_contains_a_deduper_failure(monkeypatch):
    def explode(*_args, **_kwargs):
        msg = "comparator blew up"
        raise RuntimeError(msg)

    monkeypatch.setattr(deduper_pair_scorer.Deduper, "score_pair", explode)

    result = await DeduperPairScorer().score_pair(incoming=_paper(), candidate=_paper())

    assert result.probability is None
    # The log has details; persisted evidence gets the exception type only.
    assert result.unscorable_reason == "Deduper raised RuntimeError"


@pytest.mark.asyncio
async def test_a_translation_failure_is_not_reported_as_unscorable(monkeypatch):
    # Adapter defects should fail loudly, not become unscorable pairs.
    out_of_range = PairScoreResult(
        probability=1.5,
        doi_mismatch_adjustment_applied=False,
        field_results={},
        label=PairLabel.DUPLICATE,
    )
    monkeypatch.setattr(
        deduper_pair_scorer.Deduper,
        "score_pair",
        lambda *_a, **_kw: out_of_range,
    )

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        await DeduperPairScorer().score_pair(incoming=_paper(), candidate=_paper())


@pytest.mark.asyncio
async def test_scores_off_the_event_loop(monkeypatch):
    scoring_threads = []
    real_score_pair = deduper_pair_scorer.Deduper.score_pair

    def record_thread(self, *args, **kwargs):
        scoring_threads.append(threading.current_thread())
        return real_score_pair(self, *args, **kwargs)

    monkeypatch.setattr(deduper_pair_scorer.Deduper, "score_pair", record_thread)

    await DeduperPairScorer().score_pair(incoming=_paper(), candidate=_paper())

    assert len(scoring_threads) == 1
    assert scoring_threads[0] is not threading.main_thread()
