"""
Reprompt validation for book catalog enrichment workflow.

Validates LLM responses for:
- Parse errors (malformed JSON)
- Valid BISAC codes
- Marketing description word count
"""

from agent_actions import reprompt_validation

# =============================================================================
# PARSE ERROR VALIDATION
# =============================================================================


@reprompt_validation(
    "Your response could not be parsed as valid JSON. "
    "Please respond with ONLY valid JSON - no markdown code blocks (```), "
    "no trailing commas, and no extra text before or after the JSON object."
)
def check_no_parse_error(response) -> bool:
    """
    Validate response has no parse errors.

    Rejects responses where JSON parsing failed (e.g., markdown-wrapped JSON,
    trailing commas, invalid syntax).

    Args:
        response: LLM response dict

    Returns:
        True if no parse error, False if _parse_error exists
    """
    # Extract dict from list if needed
    if isinstance(response, list):
        if not response:
            return False
        response = response[0]

    # Check for parse error field
    if "_parse_error" in response:
        print(f"[Validation] Parse error detected: {response.get('_parse_error')}")
        return False

    # Check for raw_response without actual content (indicates parsing failed)
    if "raw_response" in response and len(response) <= 2:
        print("[Validation] Response only contains raw_response - parsing likely failed")
        return False

    return True


# =============================================================================
# BISAC CODE VALIDATION
# =============================================================================


@reprompt_validation(
    "Your response must include a valid BISAC code. "
    "A BISAC code is exactly 9 characters (e.g., 'FIC000000' for General Fiction). "
    "Please provide a primary_bisac_code field with a valid 9-character code."
)
def check_valid_bisac(response) -> bool:
    """
    Validate response has valid BISAC classification.

    Args:
        response: LLM response dict

    Returns:
        True if has valid 9-character BISAC code
    """
    # Extract dict from list if needed
    if isinstance(response, list):
        if not response:
            return False
        response = response[0]

    # Check for parse errors first
    if "_parse_error" in response:
        return False

    # Check for primary_bisac_code field
    bisac_code = response.get("primary_bisac_code", "")

    if not bisac_code:
        print("[Validation] Missing primary_bisac_code field")
        return False

    if not isinstance(bisac_code, str):
        print(f"[Validation] primary_bisac_code must be string, got {type(bisac_code)}")
        return False

    if len(bisac_code) != 9:
        print(f"[Validation] BISAC code must be 9 chars, got {len(bisac_code)}: '{bisac_code}'")
        return False

    print(f"[Validation] Valid BISAC code: {bisac_code}")
    return True


# =============================================================================
# COMBINED VALIDATION (Parse + BISAC)
# =============================================================================


@reprompt_validation(
    "Your response must be valid JSON with a proper BISAC classification. "
    "Requirements: (1) No markdown code blocks or trailing commas, "
    "(2) Include primary_bisac_code as a 9-character string (e.g., 'FIC000000'). "
    "Respond with ONLY the JSON object."
)
def check_genre_classification(response) -> bool:
    """
    Combined validation for genre classification action.

    Validates both JSON parsing and BISAC code format.

    Args:
        response: LLM response dict

    Returns:
        True if valid JSON with proper BISAC code
    """
    # Extract dict from list if needed
    if isinstance(response, list):
        if not response:
            return False
        response = response[0]

    # Check for parse errors
    if "_parse_error" in response:
        print(f"[Validation] Parse error: {response.get('_parse_error')}")
        return False

    # Check for BISAC code
    bisac_code = response.get("primary_bisac_code", "")

    if not bisac_code or not isinstance(bisac_code, str) or len(bisac_code) != 9:
        print(f"[Validation] Invalid BISAC code: '{bisac_code}'")
        return False

    print(f"[Validation] Genre classification valid - BISAC: {bisac_code}")
    return True


# =============================================================================
# MARKETING DESCRIPTION VALIDATION
# =============================================================================


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

    # Check for parse errors first
    if "_parse_error" in response:
        return False

    # Get marketing_description field
    description = response.get("marketing_description", "")

    # Count words - validation PASSES when >= 50 words
    word_count = len(description.split())
    print(f"[Validation] Word count: {word_count}, Required: >= 50")
    is_valid = word_count >= 50
    print(f"[Validation] Result: {'PASS' if is_valid else 'FAIL'}")
    return is_valid
