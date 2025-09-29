"""User-defined validator for poem word count validation."""

from typing import Any, Dict, Tuple


def poem_word_count_validator(response: Any, expected: int = 5, **kwargs) -> Tuple[bool, str | None]:
    """Validate that poem content has exactly the expected number of words.

    This validator extracts the poem from the response and validates word count.

    Args:
        response: The raw API response (can be dict, list, or string)
        expected: Expected number of words (default: 5)
        **kwargs: Additional context from the interceptor

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Extract content based on response structure
    content = ""

    if isinstance(response, dict):
        # Look for poem field in dict response
        content = response.get("poem", "")
        if not content:
            # Try other common fields
            content = response.get("content", "") or response.get("text", "")
    elif isinstance(response, list) and response:
        # If list, get first item
        first_item = response[0]
        if isinstance(first_item, dict):
            content = first_item.get("poem", "") or first_item.get("content", "")
        else:
            content = str(first_item)
    elif isinstance(response, str):
        content = response
    else:
        content = str(response)

    if not content:
        return False, "No poem content found in response"

    # Count words
    word_count = len(content.split())

    if word_count == expected:
        return True, None

    return False, f"Expected {expected} words in poem, got {word_count}"