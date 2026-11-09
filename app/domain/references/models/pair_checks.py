"""
Checks that veto Deduper matches between series items or generic titles.

Decisions depend on them: changing a check needs a new ACTING_POLICY_GENERATION.
"""

import re
from collections import Counter
from collections.abc import Callable

from destiny_deduper.regexes import HTML_TAG_RE
from destiny_deduper.utils import roman_to_int
from rapidfuzz import fuzz

from app.domain.references.models.models import DeduplicationPaper, PairCheck

_WORD = re.compile(r"\w+")
_DIGITS = re.compile(r"\d+")
_ROMAN = re.compile(
    r"^(?=[MDCLXVI])M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
)
# After one of these words a numeral counts in any case and at any length; elsewhere
# "I" is usually a pronoun or an initial, and lowercase "mix" or "ml" a word.
_NUMBERING_WORDS = frozenset(
    {
        "band",
        "book",
        "chapter",
        "experiment",
        "grade",
        "issue",
        "libro",
        "livro",
        "part",
        "partie",
        "phase",
        "series",
        "série",
        "stage",
        "study",
        "teil",
        "tome",
        "type",
        "vol",
        "volume",
        "wave",
        "წიგნი",
    }
)
_MAX_SWAPPED_WORDS = 2
# Below this rapidfuzz ratio two words are unrelated rather than spelt differently.
_UNRELATED_WORD_RATIO = 60
_MAX_SHORT_TITLE_WORDS = 4


def _plain(title: str | None) -> str:
    return HTML_TAG_RE.sub(" ", title or "")


def _words(title: str | None) -> list[str]:
    return [word.lower() for word in _WORD.findall(_plain(title))]


def _read(words: list[str], i: int) -> tuple[tuple[str, ...], str | None]:
    """Return the numbers in a word, and its value when the whole word is a numeral."""
    word = words[i]
    after_numbering_word = i > 0 and words[i - 1].lower() in _NUMBERING_WORDS
    if (
        _ROMAN.match(word.upper() if after_numbering_word else word)
        and (len(word) > 1 or i == len(words) - 1 or after_numbering_word)
        and (value := roman_to_int(word))
    ):
        return (str(value),), str(value)
    # Compared as strings: int() refuses digit runs past Python's conversion limit.
    numbers = tuple(digits.lstrip("0") or "0" for digits in _DIGITS.findall(word))
    return numbers, numbers[0] if word.isdecimal() else None


def _tokens(title: str | None) -> list[tuple[str, tuple[str, ...], str | None]]:
    words = _WORD.findall(_plain(title))
    return [(word.lower(), *_read(words, i)) for i, word in enumerate(words)]


def _numbers(title: str | None) -> Counter[str]:
    return Counter(number for _, numbers, _ in _tokens(title) for number in numbers)


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
    incoming_tokens, candidate_tokens = (
        _tokens(incoming.title),
        _tokens(candidate.title),
    )
    if len(incoming_tokens) != len(candidate_tokens):
        return False
    swaps = [
        (a, b)
        for (a, _, a_numeral), (b, _, b_numeral) in zip(
            incoming_tokens, candidate_tokens, strict=True
        )
        # The same number written two ways, such as "II" and "2", is not a swap.
        if a != b and not (a_numeral is not None and a_numeral == b_numeral)
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
    """Return the checks a scored pair fails; failing any one vetoes the pair."""
    return [check for check, fails in _CHECKS.items() if fails(incoming, candidate)]
