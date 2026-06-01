"""Regex patterns and utilities for the Destiny application."""

import re
import unicodedata

_camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")

UNICODE_LETTER_PATTERN = re.compile(r"[^\W\d_]+", flags=re.UNICODE)


def is_meaningful_token(token: str, min_token_length: int) -> bool:
    """
    Check whether a name token carries enough signal for matching.

    Keeps tokens at or above *min_token_length*, plus single-character
    non-Latin tokens (e.g. CJK ideographs).  Single-character Latin
    letters — including accented ones like "É" — are treated as initials
    and excluded.
    """
    if len(token) >= min_token_length:
        return True

    if len(token) != 1:
        return False

    # Preserve single-character non-Latin tokens (e.g., CJK names),
    # but exclude Latin initials even when accented.
    return "LATIN" not in unicodedata.name(token, "")


def camel_to_snake(s: str) -> str:
    """Convert a camelCase or PascalCase string to snake_case."""
    return _camel_case_pattern.sub("_", s).casefold()
