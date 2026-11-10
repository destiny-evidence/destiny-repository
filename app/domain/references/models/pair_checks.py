"""
Checks that veto a Deduper match its title and authors do not confirm.

Decisions depend on them: changing a check needs a new ACTING_POLICY_GENERATION.
"""

import html
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable

from app.domain.references.models.models import DeduplicationPaper, PairCheck

_WORD = re.compile(r"\w+")
_ALPHANUMERIC = re.compile(r"[^\W_]+")
_NOT_ALPHANUMERIC = re.compile(r"[\W_]+")
# Tags open with a letter or "/", so "aged <5 versus >10" keeps its numbers.
_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
# Chinese, Japanese and Korean characters are whole name parts, not initials.
_WHOLE_CHARACTER_SCRIPTS = ("CJK", "HIRAGANA", "KATAKANA", "HANGUL")
_MAX_SHORT_TITLE_WORDS = 4


def _text(value: str | None) -> str:
    # Encodings of the same text match: "&amp;" and "&", or "é" composed or not.
    return unicodedata.normalize("NFKC", html.unescape(value or "")).casefold()


def _plain(title: str | None) -> str:
    return _TAG.sub(" ", _text(title))


def _titles_differ(incoming: DeduplicationPaper, candidate: DeduplicationPaper) -> bool:
    # Spacing is ignored, so "Bi-Level" and "Bilevel" or "SiO_x_" and "SiOx" match.
    return _NOT_ALPHANUMERIC.sub("", _plain(incoming.title)) != _NOT_ALPHANUMERIC.sub(
        "", _plain(candidate.title)
    )


def _parts(name: str) -> frozenset[str]:
    # Initials are left out, so "D. Álvarez" and "Daniel Álvarez" agree.
    return frozenset(
        part
        for part in _ALPHANUMERIC.findall(_text(name))
        if len(part) > 1
        or part.isdigit()
        or unicodedata.name(part, "").startswith(_WHOLE_CHARACTER_SCRIPTS)
    )


def _names(paper: DeduplicationPaper) -> list[frozenset[str]]:
    """Each author's name parts, leaving out names with none, such as "L." or "-"."""
    names = (_parts(author.display_name) for author in paper.authors or [])
    return [name for name in names if name]


def _latin(paper: DeduplicationPaper) -> set[bool]:
    # Whether each name's parts have Latin letters, accented ones such as "Đỗ"
    # included; initials are not parts, so "É. 王" is not Latin.
    return {
        any("LATIN" in unicodedata.name(char, "") for char in "".join(name))
        for name in _names(paper)
    }


def _any_name_within(names: list[frozenset[str]], others: list[frozenset[str]]) -> bool:
    # Indexed by part, since a list can name thousands of authors. A name within
    # another holds all its parts, so searching its rarest part's names is enough.
    holders: defaultdict[str, list[frozenset[str]]] = defaultdict(list)
    for other in others:
        for part in other:
            holders[part].append(other)
    return any(
        any(name <= other for other in min((holders[part] for part in name), key=len))
        for name in names
    )


def _authors_disagree(
    incoming: DeduplicationPaper, candidate: DeduplicationPaper
) -> bool:
    incoming_names, candidate_names = _names(incoming), _names(candidate)
    if not incoming_names or not candidate_names:
        return True
    # Names with and without Latin letters cannot be compared, so the authors are
    # unknown rather than disagreeing.
    if len(_latin(incoming) | _latin(candidate)) > 1:
        return False
    return not (
        _any_name_within(incoming_names, candidate_names)
        or _any_name_within(candidate_names, incoming_names)
    )


def _short_title_dois_differ(
    incoming: DeduplicationPaper, candidate: DeduplicationPaper
) -> bool:
    return (
        incoming.doi is not None
        and candidate.doi is not None
        and incoming.doi.identifier != candidate.doi.identifier
        and min(
            len(_WORD.findall(_plain(paper.title))) for paper in (incoming, candidate)
        )
        <= _MAX_SHORT_TITLE_WORDS
    )


_CHECKS: dict[PairCheck, Callable[[DeduplicationPaper, DeduplicationPaper], bool]] = {
    PairCheck.TITLES_DIFFER: _titles_differ,
    PairCheck.AUTHORS_DISAGREE: _authors_disagree,
    PairCheck.SHORT_TITLE_DOIS_DIFFER: _short_title_dois_differ,
}


def failed_pair_checks(
    incoming: DeduplicationPaper, candidate: DeduplicationPaper
) -> list[PairCheck]:
    """Return the checks a scored pair fails; failing any one vetoes the pair."""
    return [check for check, fails in _CHECKS.items() if fails(incoming, candidate)]
