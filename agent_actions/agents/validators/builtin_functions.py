"""Built-in validator functions for ValidationInterceptor.

This module provides commonly used validator functions that replace the old 
ValidatorRegistry system. These functions maintain backward compatibility 
with the same validation logic as before.
"""

from typing import List, Tuple


def word_count_validator(content: str, expected: int = 5) -> Tuple[bool, str | None]:
    """Validate that content has exactly the expected number of words.
    
    Args:
        content: The text content to validate
        expected: Expected number of words (default: 5)
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> word_count_validator("This has five words", expected=5)
        (True, None)
        >>> word_count_validator("Too many words here", expected=3)
        (False, "Expected 3 words, got 4")
    """
    word_count = len(content.split())
    if word_count == expected:
        return True, None
    return False, f"Expected {expected} words, got {word_count}"


def char_count_validator(
    content: str, *, min_chars: int = 0, max_chars: int | None = None
) -> Tuple[bool, str | None]:
    """Validate character count is within range.
    
    Args:
        content: The text content to validate
        min_chars: Minimum number of characters (default: 0)
        max_chars: Maximum number of characters (optional)
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> char_count_validator("Hello", min_chars=3, max_chars=10)
        (True, None)
        >>> char_count_validator("Hi", min_chars=5)
        (False, "Too short: 2 chars, minimum 5")
    """
    char_count = len(content)
    if char_count < min_chars:
        return False, f"Too short: {char_count} chars, minimum {min_chars}"
    if max_chars and char_count > max_chars:
        return False, f"Too long: {char_count} chars, maximum {max_chars}"
    return True, None


def keywords_validator(content: str, required_keywords: List[str]) -> Tuple[bool, str | None]:
    """Validate that content contains all required keywords.
    
    Args:
        content: The text content to validate
        required_keywords: List of keywords that must be present
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> keywords_validator("Product features and benefits", ["features", "benefits"])
        (True, None)
        >>> keywords_validator("Just features", ["features", "benefits", "price"])
        (False, "Missing required keywords: benefits, price")
    """
    content_lower = content.lower()
    missing = [kw for kw in required_keywords if kw.lower() not in content_lower]
    if missing:
        return False, f"Missing required keywords: {', '.join(missing)}"
    return True, None