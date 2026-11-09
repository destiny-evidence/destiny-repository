import pytest
from destiny_sdk.enhancements import AuthorPosition, Authorship
from destiny_sdk.identifiers import DOIIdentifier

from app.domain.references.models.models import DeduplicationPaper, PairCheck
from app.domain.references.models.pair_checks import failed_pair_checks

TITLE = PairCheck.TITLES_DIFFER
AUTHOR = PairCheck.AUTHORS_DISAGREE
SHORT_TITLE = PairCheck.SHORT_TITLE_DOIS_DIFFER


def _paper(
    title: str | None,
    doi: str | None = None,
    authors: tuple[str, ...] = ("Ada Lovelace",),
) -> DeduplicationPaper:
    return DeduplicationPaper(
        title=title,
        doi=DOIIdentifier(identifier=doi) if doi else None,
        authors=[
            Authorship(
                display_name=name,
                position=AuthorPosition.FIRST if i == 0 else AuthorPosition.MIDDLE,
            )
            for i, name in enumerate(authors)
        ]
        or None,
    )


@pytest.mark.parametrize(
    ("incoming", "candidate", "expected"),
    [
        pytest.param(
            _paper("Newsletter Issue 3"),
            _paper("Newsletter Issue 4"),
            [TITLE],
            id="series number",
        ),
        pytest.param(
            _paper(None),
            _paper("Newsletter Issue 3"),
            [TITLE],
            id="incoming has no title",
        ),
        pytest.param(
            _paper("Notes on the <i>Contributors</i>"),
            _paper("Notes on the contributors."),
            [],
            id="case, markup and punctuation",
        ),
        pytest.param(
            _paper("Bi-Level Draft Guidance on SiO_x_"),
            _paper("Bilevel DraftGuidance on SiOx"),
            [],
            id="spacing and underscores",
        ),
        pytest.param(
            _paper("Señor Don Mariano Riva Palacio", authors=("Manuel Moral",)),
            _paper("Señor Don Mariano Riva Palacio", authors=("Manuel Payno",)),
            [AUTHOR],
            id="same title, different writer",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("D. Álvarez González",)),
            _paper("Sleep apnoea screening", authors=("Daniel Álvarez González",)),
            [],
            id="incoming first author abbreviated",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("Daniel Álvarez González",)),
            _paper("Sleep apnoea screening", authors=("Álvarez González",)),
            [],
            id="candidate first author shortened",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("Ada Lovelace", "Alan Turing")),
            _paper("Sleep apnoea screening", authors=("Alan Turing", "Ada Lovelace")),
            [],
            id="author order ignored",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("Ada Lovelace", "Alan Turing")),
            _paper("Sleep apnoea screening", authors=("Grace Hopper", "Alan Turing")),
            [],
            id="a co-author agrees",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("Manuel Moral", "-")),
            _paper("Sleep apnoea screening", authors=("Manuel Payno",)),
            [AUTHOR],
            id="a name without parts is left out",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("A. L.",)),
            _paper("Sleep apnoea screening", authors=("Ada Lovelace",)),
            [AUTHOR],
            id="initials only",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=()),
            _paper("Sleep apnoea screening", authors=("Ada Lovelace", "山田 太郎")),
            [AUTHOR],
            id="incoming has no authors",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("Ada Lovelace", "山田 太郎")),
            _paper("Sleep apnoea screening", authors=()),
            [AUTHOR],
            id="candidate has no authors",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("Naofumi Kishimoto",)),
            _paper("Sleep apnoea screening", authors=("直文 岸本",)),
            [],
            id="romanised name against kanji",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("直文 岸本",)),
            _paper("Sleep apnoea screening", authors=("公章 森",)),
            [AUTHOR],
            id="different names in kanji",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("Hironori Midorikawa",)),
            _paper("Sleep apnoea screening", authors=("裕紀 緑川", "Yusuke Suzuki")),
            [],
            id="conflict beside a name that cannot be compared",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("裕紀 緑川", "Ada Lovelace")),
            _paper("Sleep apnoea screening", authors=("山田 太郎", "Alan Turing")),
            [],
            id="both lists mix scripts",
        ),
        pytest.param(
            _paper("Preliminary Material", "10.1163/1-001"),
            _paper("Preliminary Material", "10.1163/2-001"),
            [SHORT_TITLE],
            id="short title under two DOIs",
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
    ],
)
def test_failed_pair_checks(incoming, candidate, expected):
    assert failed_pair_checks(incoming, candidate) == expected
