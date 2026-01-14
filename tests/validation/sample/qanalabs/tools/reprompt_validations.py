"""
Reprompt validation for book catalog enrichment workflow.

Validates that marketing descriptions meet minimum word count.
"""

from agent_actions import reprompt_validation


@reprompt_validation(
    "Your marketing_description must have at least 50 words. "
    "Please write a more detailed and compelling description that fully captures "
    "the value proposition and key benefits of this book."
)
def check_description_word_count(response) -> bool:
    """
    Validate marketing description has minimum 50 words.

    Args:
        response: LLM response (list with dict inside)

    Returns:
        True if marketing_description has >= 50 words
    """
    # Extract dict from list (LLM returns list with one dict)
    if isinstance(response, list):
        if not response:
            return False
        response = response[0]

    # Get marketing_description field
    description = response.get("marketing_description", "")

    # Count words - validation PASSES when >= 50 words
    word_count = len(description.split())
    print(f"[Validation] Word count: {word_count}, Required: 50")
    return word_count >= 50
