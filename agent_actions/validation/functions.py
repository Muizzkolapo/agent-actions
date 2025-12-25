"""Validator functions for use with ValidationInterceptor."""

from typing import List, Tuple


def validate_word_count(content: str, expected: int = 5) -> Tuple[bool, str | None]:
    """Validate that content has exactly the expected number of words."""
    word_count = len(content.split())
    if word_count == expected:
        return True, None
    return False, f"Expected {expected} words, got {word_count}"


def validate_char_count(
    content: str, *, min_chars: int = 0, max_chars: int | None = None
) -> Tuple[bool, str | None]:
    """Validate character count is within range."""
    char_count = len(content)
    if char_count < min_chars:
        return False, f"Too short: {char_count} chars, minimum {min_chars}"
    if max_chars and char_count > max_chars:
        return False, f"Too long: {char_count} chars, maximum {max_chars}"
    return True, None


def validate_keywords(content: str, required_keywords: List[str]) -> Tuple[bool, str | None]:
    """Validate that content contains all required keywords."""
    content_lower = content.lower()
    missing = [kw for kw in required_keywords if kw.lower() not in content_lower]
    if missing:
        return False, f"Missing required keywords: {', '.join(missing)}"
    return True, None
