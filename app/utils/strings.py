"""Utility functions for string operations."""

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
