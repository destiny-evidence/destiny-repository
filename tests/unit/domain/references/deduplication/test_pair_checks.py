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
            _paper("Notes on the <i>Contributors</i> &amp; Editors"),
            _paper("Notes on the contributors & editors."),
            [],
            id="case, markup, entities and punctuation",
        ),
        pytest.param(
            _paper("Children aged &lt;5 versus &gt;10 years"),
            _paper("Children aged &lt;8 versus &gt;10 years"),
            [TITLE],
            id="angle brackets that are not markup",
        ),
        pytest.param(
            _paper("CO₂ levels in a café on the Straße"),
            _paper("CO2 levels in a cafe\u0301 on the STRASSE"),
            [],
            id="Unicode forms and case folding",
        ),
        pytest.param(
            _paper("Bi-Level Draft Guidance on SiO_x_"),
            _paper("Bilevel DraftGuidance on SiOx"),
            [],
            id="spacing and underscores",
        ),
        pytest.param(
            _paper("काल", authors=("राम कुमार",)),
            _paper("काल", authors=("राम कुमार",)),
            [],
            id="vowel signs belong to their letters",
        ),
        pytest.param(
            _paper("कल"),
            _paper("काल"),
            [TITLE],
            id="titles differing by a vowel sign",
        ),
        pytest.param(
            _paper("Let's not forget them"),
            _paper("Let\u00b4s not forget them"),
            [],
            id="spacing accent as an apostrophe",
        ),
        pytest.param(
            _paper("Fenomenología e Historia", authors=("William R. Darós",)),
            _paper("Fenomenologia e historia", authors=("W. R. Daros",)),
            [],
            id="accents on Latin letters",
        ),
        pytest.param(
            _paper("Мой"),
            _paper("Мои"),
            [TITLE],
            id="a mark that makes another letter",
        ),
        pytest.param(
            _paper("Señor Don Mariano Riva Palacio", authors=("Manuel Moral",)),
            _paper("Señor Don Mariano Riva Palacio", authors=("Manuel Payno",)),
            [AUTHOR],
            id="same title, different writer",
        ),
        pytest.param(
            _paper("Analytic summary", authors=("Secretaría de Redacción 6",)),
            _paper("Analytic summary", authors=("Secretaría de Redacción 5",)),
            [AUTHOR],
            id="numbers in a name",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("D. Álvarez González",)),
            _paper("Sleep apnoea screening", authors=("Daniel Álvarez González",)),
            [],
            id="incoming first author abbreviated",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("Й. Смірнова",)),
            _paper("Sleep apnoea screening", authors=("Йосип Смірнова",)),
            [],
            id="Cyrillic initial",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("מ. כהן",)),
            _paper("Sleep apnoea screening", authors=("משה כהן",)),
            [],
            id="Hebrew initial",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("J. Smith",)),
            _paper("Sleep apnoea screening", authors=("A. Smith",)),
            [AUTHOR],
            id="initials that differ",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("J. A. Smith",)),
            _paper("Sleep apnoea screening", authors=("John Smith",)),
            [],
            id="the shorter name has another initial",
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
            _paper(
                "Sleep apnoea screening",
                authors=("\uff37\uff41\uff4e\uff47 \uff37\uff45\uff49",),
            ),
            _paper("Sleep apnoea screening", authors=("Li Na",)),
            [AUTHOR],
            id="full-width Latin is Latin",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("&#272;&#7895;",)),
            _paper("Sleep apnoea screening", authors=("Nguy\u1ec5n",)),
            [AUTHOR],
            id="accented Latin is Latin, even as entities",
        ),
        pytest.param(
            _paper("Sleep apnoea screening", authors=("娜 刘",)),
            _paper("Sleep apnoea screening", authors=("娜 刘",)),
            [],
            id="one-character name parts",
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
            _paper("Notes on the Contributors", "10.1163/1-001"),
            _paper("Notes on the Contributors", "10.1163/2-001"),
            [SHORT_TITLE],
            id="four-word title under two DOIs",
        ),
        pytest.param(
            _paper("Newsletter of the Co-operative", "10.1163/1-001"),
            _paper("Newsletter of the Cooperative", "10.1163/2-001"),
            [SHORT_TITLE],
            id="four words on one side under two DOIs",
        ),
        pytest.param(
            _paper("Notes on the Contributors", "10.1163/1-001"),
            _paper("Notes on the Contributors", "10.1163/1-001"),
            [],
            id="shared DOI",
        ),
        pytest.param(
            _paper("Notes on the Contributors", "10.1163/1-001"),
            _paper("Notes on the Contributors"),
            [],
            id="candidate DOI missing",
        ),
        pytest.param(
            _paper("Notes on the Contributors"),
            _paper("Notes on the Contributors", "10.1163/1-001"),
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
            _paper("Newsletter Issue 3", "10.1163/1-001", ("Manuel Moral",)),
            _paper("Newsletter Issue 4", "10.1163/2-001", ("Manuel Payno",)),
            [TITLE, AUTHOR, SHORT_TITLE],
            id="every failing check is listed",
        ),
    ],
)
def test_failed_pair_checks(incoming, candidate, expected):
    assert failed_pair_checks(incoming, candidate) == expected
