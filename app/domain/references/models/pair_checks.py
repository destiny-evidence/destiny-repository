"""
Checks that veto a Deduper match its title and authors do not confirm.

Decisions depend on them: changing a check needs a new ACTING_POLICY_GENERATION.
"""

import re
from collections import defaultdict
from collections.abc import Callable

from destiny_deduper.regexes import HTML_TAG_RE

from app.domain.references.models.models import DeduplicationPaper, PairCheck

_WORD = re.compile(r"\w+")
_NOT_ALPHANUMERIC = re.compile(r"[\W_]+")
# Initials are left out, so "D. Álvarez" and "Daniel Álvarez" agree.
_NAME_PART = re.compile(r"\w{2,}")
# Only separates names with ASCII Latin letters from names without, such as kanji.
_LATIN = re.compile(r"[A-Za-z]")
_MAX_SHORT_TITLE_WORDS = 4


def _plain(title: str | None) -> str:
    return HTML_TAG_RE.sub(" ", title or "").lower()


def _titles_differ(incoming: DeduplicationPaper, candidate: DeduplicationPaper) -> bool:
    # Spacing is ignored, so "Bi-Level" and "Bilevel" or "SiO_x_" and "SiOx" match.
    return _NOT_ALPHANUMERIC.sub("", _plain(incoming.title)) != _NOT_ALPHANUMERIC.sub(
        "", _plain(candidate.title)
    )


def _names(paper: DeduplicationPaper) -> list[frozenset[str]]:
    """Each author's name parts, leaving out names with none, such as "L." or "-"."""
    names = (
        frozenset(part.lower() for part in _NAME_PART.findall(author.display_name))
        for author in paper.authors or []
    )
    return [name for name in names if name]


def _latin(paper: DeduplicationPaper) -> set[bool]:
    return {
        bool(_LATIN.search(author.display_name))
        for author in paper.authors or []
        if _NAME_PART.search(author.display_name)
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
        and len(_WORD.findall(_plain(incoming.title))) <= _MAX_SHORT_TITLE_WORDS
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
