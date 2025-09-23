from agent_actions.validators.registry import ValidatorRegistry
from agent_actions.validators.registry import ValidatorRegistry, validate_word_count
from typing import Tuple

@ValidatorRegistry.register("word_count")
def validate_word_count(content: str, expected: int = 5) -> Tuple[bool, str | None]:
    """Validate that content has exactly the expected number of words."""
    word_count = len(content.split())

    # Debug prints
    print(f"🔍 VALIDATION DEBUG:")
    print(f"   Content: '{content[:100]}...' (first 100 chars)")
    print(f"   Word count: {word_count}, Expected: {expected}")

    if word_count == expected:
        print(f"   ✅ VALIDATION PASSED")
        return True, None
    else:
        print(f"   ❌ VALIDATION FAILED - will retry with improved prompt")
        return False, f"Expected {expected} words, got {word_count}"