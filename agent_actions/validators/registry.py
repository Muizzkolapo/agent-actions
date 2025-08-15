from __future__ import annotations

"""Registry for validation functions used by interceptors."""

from typing import Callable, Dict, List, Tuple


class ValidatorRegistry:
    """Registry for validation functions."""

    _validators: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a validator function."""

        def decorator(func: Callable) -> Callable:
            cls._validators[name] = func
            return func

        return decorator

    @classmethod
    def get(cls, name: str) -> Callable | None:
        """Get a validator by name."""

        return cls._validators.get(name)

    @classmethod
    def list_validators(cls) -> List[str]:
        """List all registered validators."""

        return list(cls._validators.keys())


@ValidatorRegistry.register("word_count")
def validate_word_count(content: str, expected: int = 5) -> Tuple[bool, str | None]:
    """Validate that content has exactly the expected number of words."""

    word_count = len(content.split())
    if word_count == expected:
        return True, None
    return False, f"Expected {expected} words, got {word_count}"


@ValidatorRegistry.register("char_count")
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


@ValidatorRegistry.register("contains_keywords")
def validate_keywords(content: str, required_keywords: List[str]) -> Tuple[bool, str | None]:
    """Validate that content contains all required keywords."""

    content_lower = content.lower()
    missing = [kw for kw in required_keywords if kw.lower() not in content_lower]
    if missing:
        return False, f"Missing required keywords: {', '.join(missing)}"
    return True, None
