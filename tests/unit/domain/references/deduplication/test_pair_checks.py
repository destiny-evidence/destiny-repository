import pytest
from destiny_sdk.identifiers import DOIIdentifier

from app.domain.references.models.models import DeduplicationPaper, PairCheck
from app.domain.references.models.pair_checks import failed_pair_checks

NUMBERS = PairCheck.NUMBERS_SWAPPED
WORDS = PairCheck.WORDS_SWAPPED
SHORT_TITLE = PairCheck.SHORT_TITLE_DOIS_DIFFER


def _paper(title: str | None, doi: str | None = None) -> DeduplicationPaper:
    return DeduplicationPaper(
        title=title, doi=DOIIdentifier(identifier=doi) if doi else None
    )


@pytest.mark.parametrize(
    ("incoming", "candidate", "expected"),
    [
        pytest.param(
            _paper("Newsletter Issue 3"),
            _paper("Newsletter Issue 4"),
            [NUMBERS, WORDS],
            id="series number",
        ),
        pytest.param(
            _paper("Part I: Methods"),
            _paper("Part II: Methods"),
            [NUMBERS],
            id="numeral after a numbering word",
        ),
        pytest.param(
            _paper("Henry I"), _paper("Henry II"), [NUMBERS], id="numeral at the end"
        ),
        pytest.param(
            _paper("Letter from C Lewis to D Jones"),
            _paper("Letter from M Lewis to D Jones"),
            [WORDS],
            id="initials are not numbers",
        ),
        pytest.param(
            _paper("Annual report"),
            _paper("Annual report 2019"),
            [],
            id="number on one side only",
        ),
        pytest.param(
            _paper("Report 007"),
            _paper("Report VII"),
            [WORDS],
            id="same number written differently",
        ),
        pytest.param(
            _paper("Lineage of the Smith family in Kent"),
            _paper("Lineage of the Jones family in Devon"),
            [WORDS],
            id="templated title, two words swapped",
        ),
        pytest.param(
            _paper("The colour of water"),
            _paper("The color of water"),
            [],
            id="spelling variant",
        ),
        pytest.param(
            _paper("A study of red green and blue"),
            _paper("A study of cats dogs and mice"),
            [],
            id="three words swapped",
        ),
        pytest.param(
            _paper("Effects of <i>exercise</i>"),
            _paper("Effects of exercise"),
            [],
            id="markup only",
        ),
        pytest.param(
            _paper("Notes on the Contributors", "10.1163/1-001"),
            _paper("Notes on the contributors", "10.1163/2-001"),
            [SHORT_TITLE],
            id="four-word generic title under two DOIs",
        ),
        pytest.param(
            _paper("Preliminary Material", "10.1163/1-001"),
            _paper("Preliminary Material", "10.1163/1-001"),
            [],
            id="shared DOI",
        ),
        pytest.param(
            _paper("Preliminary Material", "10.1163/1-001"),
            _paper("Preliminary Material"),
            [],
            id="candidate DOI missing",
        ),
        pytest.param(
            _paper("Preliminary Material"),
            _paper("Preliminary Material", "10.1163/1-001"),
            [],
            id="incoming DOI missing",
        ),
        pytest.param(
            _paper("Notes on the five sources", "10.1163/1-001"),
            _paper("Notes on the five sources", "10.1163/2-001"),
            [],
            id="title longer than four words",
        ),
        pytest.param(
            _paper("Front matter", "10.1163/1-001"),
            _paper("Back matter", "10.1163/2-001"),
            [WORDS],
            id="different short titles",
        ),
        pytest.param(
            _paper(None, "10.1163/1-001"),
            _paper("Newsletter Issue 3"),
            [],
            id="no title",
        ),
        pytest.param(
            _paper(None, "10.1163/1-001"),
            _paper(None, "10.1163/2-001"),
            [],
            id="no titles under two DOIs",
        ),
        pytest.param(
            _paper("Table " + "1" * 4301),
            _paper("Table " + "1" * 4301),
            [],
            id="number longer than int conversion allows",
        ),
    ],
)
def test_failed_pair_checks(incoming, candidate, expected):
    assert failed_pair_checks(incoming, candidate) == expected
