"""Regex patterns and utilities for the Destiny application."""

import re

_camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")


def camel_to_snake(s: str) -> str:
    """Convert a camelCase or PascalCase string to snake_case."""
    return _camel_case_pattern.sub("_", s).casefold()
