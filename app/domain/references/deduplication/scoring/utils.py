"""Utility functions for deduplication scoring."""

import re

# Pre-compiled regex for tokenization - extracts alphanumeric sequences
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)

# Pattern to strip XML/HTML tags (including MathML)
_TAG_PATTERN = re.compile(r"<[^>]+>")


def tokenize(text: str | None) -> list[str]:
    """
    Extract lowercase alphanumeric tokens from text.

    Strips XML/HTML tags (including MathML) before tokenization to avoid
    false positive matches on common tag tokens like "mml", "math", "xmlns".

    Ignores punctuation and returns lowercased tokens.
    Empty or None input returns an empty list.

    Args:
        text: Text to tokenize.

    Returns:
        List of lowercase alphanumeric tokens.

    Examples:
        >>> tokenize("Hello, World!")
        ['hello', 'world']
        >>> tokenize("Einleitung.")
        ['einleitung']
        >>> tokenize(None)
        []
        >>> tokenize('<mml:math xmlns:mml="http://www.w3.org/...">x</mml:math>')
        ['x']

    """
    if not text:
        return []
    # Strip XML/HTML tags before tokenization
    clean_text = _TAG_PATTERN.sub(" ", text)
    return [tok.lower() for tok in _TOKEN_PATTERN.findall(clean_text)]


def title_token_jaccard(t1: str | None, t2: str | None) -> float:
    """
    Compute Jaccard similarity on title tokens.

    This is a fast, simple measure of title similarity that works well
    for duplicate detection when combined with ES BM25 scores.

    Tokenization extracts alphanumeric sequences (ignoring punctuation),
    so "Einleitung." and "Einleitung" are treated as the same token.

    Args:
        t1: First title string.
        t2: Second title string.

    Returns:
        Jaccard similarity (0.0 to 1.0).

    Examples:
        >>> title_token_jaccard("Hello World", "Hello World")
        1.0
        >>> title_token_jaccard("Hello World", "Hello")
        0.5
        >>> title_token_jaccard("Einleitung.", "Einleitung")
        1.0
        >>> title_token_jaccard(None, "Hello")
        0.0

    """
    if not t1 or not t2:
        return 0.0

    tokens1 = set(tokenize(t1))
    tokens2 = set(tokenize(t2))

    if not tokens1 or not tokens2:
        return 0.0

    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)

    return intersection / union
