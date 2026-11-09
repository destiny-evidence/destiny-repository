"""Checks that hold apart series items and generic titles the Deduper matches."""

import re
from collections import Counter
from collections.abc import Callable
from enum import StrEnum, auto

from destiny_deduper.utils import roman_to_int
from rapidfuzz import fuzz

from app.domain.references.models.models import DeduplicationPaper

_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"\w+")
_DIGITS = re.compile(r"\d+")
_ROMAN = re.compile(
    r"^(?=[MDCLXVI])M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
)
# A one-letter numeral such as "I" is a number only at the end of a title or after
# one of these words; elsewhere it is usually a pronoun or an initial.
_NUMBERING_WORDS = frozenset(
    {
        "band",
        "book",
        "chapter",
        "libro",
        "livro",
        "part",
        "partie",
        "series",
        "série",
        "teil",
        "tome",
        "vol",
        "volume",
        "წიგნი",
    }
)
_MAX_SWAPPED_WORDS = 2
# Below this rapidfuzz ratio two words are unrelated rather than spelt differently.
_UNRELATED_WORD_RATIO = 60
_MAX_SHORT_TITLE_WORDS = 4


class PairCheck(StrEnum):
    """A rule that holds apart a pair the Deduper scored at or above its threshold."""

    NUMBERS_SWAPPED = auto()
    """Each title carries a number the other lacks, as items in a numbered series do."""
    WORDS_SWAPPED = auto()
    """The titles differ by one or two unrelated words, as templated titles do."""
    SHORT_TITLE_DOIS_DIFFER = auto()
    """A short identical title under two different DOIs, as generic titles are."""


def _words(title: str | None) -> list[str]:
    return [word.lower() for word in _WORD.findall(_TAG.sub(" ", title or ""))]


def _numbers(title: str | None) -> Counter[str]:
    text = _TAG.sub(" ", title or "")
    # Compared as strings: int() refuses digit runs past Python's conversion limit.
    numbers = Counter(digits.lstrip("0") or "0" for digits in _DIGITS.findall(text))
    words = _WORD.findall(text)
    for i, word in enumerate(words):
        if (
            _ROMAN.match(word)
            and (
                len(word) > 1
                or i == len(words) - 1
                or (i > 0 and words[i - 1].lower() in _NUMBERING_WORDS)
            )
            and (value := roman_to_int(word))
        ):
            numbers[str(value)] += 1
    return numbers


def _numbers_swapped(
    incoming: DeduplicationPaper, candidate: DeduplicationPaper
) -> bool:
    incoming_numbers, candidate_numbers = (
        _numbers(incoming.title),
        _numbers(candidate.title),
    )
    return bool(incoming_numbers - candidate_numbers) and bool(
        candidate_numbers - incoming_numbers
    )


def _words_swapped(incoming: DeduplicationPaper, candidate: DeduplicationPaper) -> bool:
    incoming_words, candidate_words = _words(incoming.title), _words(candidate.title)
    if len(incoming_words) != len(candidate_words):
        return False
    swaps = [
        (a, b) for a, b in zip(incoming_words, candidate_words, strict=True) if a != b
    ]
    return 0 < len(swaps) <= _MAX_SWAPPED_WORDS and all(
        fuzz.ratio(a, b) < _UNRELATED_WORD_RATIO for a, b in swaps
    )


def _short_title_dois_differ(
    incoming: DeduplicationPaper, candidate: DeduplicationPaper
) -> bool:
    words = _words(incoming.title)
    return (
        incoming.doi is not None
        and candidate.doi is not None
        and incoming.doi.identifier != candidate.doi.identifier
        and words == _words(candidate.title)
        and 0 < len(words) <= _MAX_SHORT_TITLE_WORDS
    )


_CHECKS: dict[PairCheck, Callable[[DeduplicationPaper, DeduplicationPaper], bool]] = {
    PairCheck.NUMBERS_SWAPPED: _numbers_swapped,
    PairCheck.WORDS_SWAPPED: _words_swapped,
    PairCheck.SHORT_TITLE_DOIS_DIFFER: _short_title_dois_differ,
}


def failed_pair_checks(
    incoming: DeduplicationPaper, candidate: DeduplicationPaper
) -> list[PairCheck]:
    """Return the checks a scored pair fails; failing any one holds the pair apart."""
    return [check for check, fails in _CHECKS.items() if fails(incoming, candidate)]
