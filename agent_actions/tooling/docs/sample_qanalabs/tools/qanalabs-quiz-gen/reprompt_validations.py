"""
Reprompt validation for quiz generation workflow.

Validates LLM responses for:
- Source quote minimum word count (30 words)
"""

from agent_actions import reprompt_validation


# =============================================================================
# SOURCE QUOTE VALIDATION
# =============================================================================

@reprompt_validation(
    "Your source_quote must be at least 30 words long. "
    "Please provide a longer, more complete quote from the source material "
    "that fully supports your answer. The quote should be a direct, exact excerpt "
    "from the documentation."
)
def check_source_quote_length(response) -> bool:
    """
    Validate source quote has minimum 30 words.

    Args:
        response: LLM response (list with dict inside)

    Returns:
        True if source_quote has >= 30 words
    """
    # Extract dict from list (LLM returns list with one dict)
    if isinstance(response, list):
        if not response:
            return False
        response = response[0]

    # Check for parse errors first
    if "_parse_error" in response:
        return False

    # Get source_quote field
    source_quote = response.get("source_quote", "")

    # Count words - validation PASSES when >= 30 words
    word_count = len(source_quote.split())
    print(f"[Validation] Source quote word count: {word_count}, Required: >= 30")
    is_valid = word_count >= 15
    print(f"[Validation] Result: {'PASS' if is_valid else 'FAIL'}")
    return is_valid
