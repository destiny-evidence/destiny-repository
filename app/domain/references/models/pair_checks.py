"""
Checks that veto a Deduper match its title and authors do not confirm.

Decisions depend on them: changing a check needs a new ACTING_POLICY_GENERATION.
"""

import html
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from typing import NamedTuple

from app.domain.references.models.models import DeduplicationPaper, PairCheck

# Tags open with a letter or "/", so "aged <5 versus >10" keeps its numbers.
_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
# Chinese, Japanese and Korean characters are whole name parts, not initials.
_WHOLE_CHARACTER_SCRIPTS = ("CJK", "HIRAGANA", "KATAKANA", "HANGUL")
# Only after a Latin letter: elsewhere a mark makes another letter, as in "й".
_LATIN_ACCENTS = re.compile(r"(?<=[a-z])[\u0300-\u036f]+")
_MAX_SHORT_TITLE_WORDS = 4


class _Name(NamedTuple):
    parts: frozenset[str]
    first_letters: frozenset[str]


def _text(value: str | None) -> str:
    # Encodings of the same text match: "&amp;" and "&", or "é", "e\u0301" and "e".
    text = unicodedata.normalize("NFKD", html.unescape(value or "")).casefold()
    return unicodedata.normalize("NFC", _LATIN_ACCENTS.sub("", text))


def _words(text: str) -> list[str]:
    # A mark stays with its letter: "\w" leaves out the vowel signs of Devanagari,
    # Tamil or Thai, which would cut "राम" into "र" and "म".
    kept: list[str] = []
    for char in text:
        kind = unicodedata.category(char)[0]
        in_word = kind in "LN" or (kind == "M" and kept[-1:] not in ([], [" "]))
        kept.append(char if in_word else " ")
    return "".join(kept).split()


def _plain(title: str | None) -> str:
    return _TAG.sub(" ", _text(title))


def _titles_differ(incoming: DeduplicationPaper, candidate: DeduplicationPaper) -> bool:
    # Spacing is ignored, so "Bi-Level" and "Bilevel" or "SiO_x_" and "SiOx" match.
    return "".join(_words(_plain(incoming.title))) != "".join(
        _words(_plain(candidate.title))
    )


def _name(display_name: str) -> _Name:
    # Initials are not parts, so "D. Álvarez" and "Daniel Álvarez" agree; first
    # letters are kept so that "J. Smith" and "A. Smith" do not.
    words = _words(_text(display_name))
    parts = frozenset(
        word
        for word in words
        if len(word) > 1
        or word.isdigit()
        or unicodedata.name(word, "").startswith(_WHOLE_CHARACTER_SCRIPTS)
    )
    return _Name(parts, frozenset(word[0] for word in words))


def _names(paper: DeduplicationPaper) -> list[_Name]:
    """Each author's name, leaving out names with no parts, such as "L." or "-"."""
    names = (_name(author.display_name) for author in paper.authors or [])
    return [name for name in names if name.parts]


def _latin(paper: DeduplicationPaper) -> set[bool]:
    # Whether each name's parts have Latin letters, accented ones such as "Đỗ"
    # included; initials are not parts, so "É. 王" is not Latin.
    return {
        any("LATIN" in unicodedata.name(char, "") for char in "".join(name.parts))
        for name in _names(paper)
    }


def _within(name: _Name, other: _Name) -> bool:
    return name.parts <= other.parts and (
        name.first_letters <= other.first_letters
        or other.first_letters <= name.first_letters
    )


def _any_name_within(names: list[_Name], others: list[_Name]) -> bool:
    # Indexed by part, since a list can name thousands of authors. A name within
    # another holds all its parts, so searching its rarest part's names is enough.
    holders: defaultdict[str, list[_Name]] = defaultdict(list)
    for other in others:
        for part in other.parts:
            holders[part].append(other)
    return any(
        any(
            _within(name, other)
            for other in min((holders[part] for part in name.parts), key=len)
        )
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
        and min(len(_words(_plain(paper.title))) for paper in (incoming, candidate))
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
