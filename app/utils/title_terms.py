"""Query-side normalisation of a title for candidate retrieval."""

import unicodedata

# Lucene's default English stop set. The title field is indexed with the standard
# analyzer, which keeps these, so a short title can satisfy minimum_should_match
# with "of" alone and match a large share of the corpus.
ENGLISH_STOPWORDS = frozenset(
    "a an and are as at be but by for if in into is it no not of on or such that "
    "the their then there these they this to was will with".split()
)

# The standard tokenizer follows the Unicode word-break rules. These characters
# stay inside a word when they sit between word characters: MidLetter between
# letters, MidNum between digits, MidNumLet between either.
_MID_LETTER = frozenset(
    map(chr, [0x003A, 0x00B7, 0x0387, 0x05F4, 0x2027, 0xFE13, 0xFE55, 0xFF1A, 0x02D7])
)
_MID_NUM = frozenset(
    map(
        chr,
        [
            0x002C,
            0x003B,
            0x037E,
            0x0589,
            0x060C,
            0x060D,
            0x066C,
            0x07F8,
            0x2044,
            0xFE10,
            0xFE14,
            0xFE50,
            0xFE54,
            0xFF0C,
            0xFF1B,
        ],
    )
)
_MID_NUM_LET = frozenset(
    map(chr, [0x002E, 0x0027, 0x2018, 0x2019, 0x2024, 0xFE52, 0xFF07, 0xFF0E])
)
_JOINERS = _MID_LETTER | _MID_NUM | _MID_NUM_LET
# ExtendNumLet characters that are not connector punctuation.
_EXTEND_NUM_LET = frozenset(map(chr, [0x202F, 0xFF3F]))


def _is_hebrew_letter(char: str) -> bool:
    return unicodedata.category(char) == "Lo" and "HEBREW" in unicodedata.name(char, "")


def _is_word_char(char: str) -> bool:
    """
    Letters, marks, digits, connectors and invisible format characters.

    Format characters (soft hyphens, zero-width joiners) are kept so they never
    end a word: the index holds such a word whole, and a split half would not
    match it.
    """
    category = unicodedata.category(char)
    return category[0] in "LMN" or category in {"Pc", "Cf"} or char in _EXTEND_NUM_LET


def title_words(title: str) -> list[str]:
    """
    Split a title where the standard analyzer splits it, or more coarsely.

    Hyphens, slashes, brackets and whitespace end a word. A joiner such as an
    apostrophe, period, colon or middle dot only does when it is not between
    word characters, so "in-vitro" is two words and "U.S.A", "Kermit's" and
    "Col·lagen" are one, as is a Hebrew acronym such as צה"ל. A format character
    such as a soft hyphen never ends a word. Where this differs from the
    analyzer it keeps characters together, which is safe because Elasticsearch
    re-splits a joined word exactly as it split the original; splitting finer
    than the analyzer would not be.
    """
    words: list[str] = []
    current: list[str] = []
    for i, char in enumerate(title):
        if _is_word_char(char):
            current.append(char)
            continue
        following = title[i + 1] if i + 1 < len(title) else ""
        joins = bool(current) and (
            (char in _JOINERS and bool(following) and _is_word_char(following))
            # Hebrew writes acronyms with a double quote between letters.
            or (
                char == '"'
                and _is_hebrew_letter(current[-1])
                and _is_hebrew_letter(following)
            )
        )
        if joins:
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def title_query_terms(title: str, *, strip_stopwords: bool, dedupe: bool) -> list[str]:
    """
    Return the title words to match, with the requested normalisation.

    Stopwords are removed and repeated words collapsed so that neither can count
    towards minimum_should_match. Elasticsearch counts each occurrence of a word
    as a separate clause, so a title repeating "de" and "la" would otherwise match
    any document containing both. An empty result means the title carries no
    searchable signal.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for word in title_words(title):
        key = word.lower()
        if strip_stopwords and key in ENGLISH_STOPWORDS:
            continue
        if dedupe:
            if key in seen:
                continue
            seen.add(key)
        kept.append(word)
    return kept
