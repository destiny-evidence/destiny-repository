"""Utility functions for string operations."""

from typing import overload

from app.utils.regex import MOJIBAKE_SIGNATURE

# Newline code points (LF, CR, NEL, LINE/PARAGRAPH SEPARATOR) that break line-based
# formats, mapped to spaces.
_NEWLINE_TO_SPACE = {
    ord("\n"): " ",
    ord("\r"): " ",
    0x85: " ",
    0x2028: " ",
    0x2029: " ",
}


def flatten_newlines(value: str) -> str:
    """Replace every newline code point with a space, keeping the text on one line."""
    return value.translate(_NEWLINE_TO_SPACE)


@overload
def demojibake(value: str) -> str: ...


@overload
def demojibake(value: None) -> None: ...


def demojibake(value: str | None) -> str | None:
    """Reverse a latin-1 misdecode of UTF-8 bytes, when the string looks mojibake'd."""
    if value is None or not MOJIBAKE_SIGNATURE.search(value):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def demojibake_walk(
    node: object, text_keys: frozenset[str], *, under_text_key: bool = False
) -> None:
    """Recursively repair mojibake in string values whose key is in text_keys."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                if key in text_keys:
                    node[key] = demojibake(value)
            else:
                demojibake_walk(value, text_keys, under_text_key=key in text_keys)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str):
                if under_text_key:
                    node[index] = demojibake(value)
            else:
                demojibake_walk(value, text_keys, under_text_key=under_text_key)
