"""Reprompt validations for contract_reviewer workflow.

Generic required-field check — validates all required schema fields
are present and non-null in the LLM response.
"""

from agent_actions import reprompt_validation


@reprompt_validation(
    "Your response is missing required fields or contains null values. "
    "Check the schema — every required field must be present and non-null. "
    "Numbers must be actual numbers, not null or strings."
)
def check_required_fields(response) -> bool:
    """Reject responses where any field is None.

    Works for any action — doesn't hardcode field names.
    Catches the common LLM failure mode of returning null for
    fields it couldn't confidently fill.
    """
    if isinstance(response, list):
        response = response[0] if response else {}
    if not isinstance(response, dict) or not response:
        return False
    if "_parse_error" in response:
        return False

    for key, val in response.items():
        if key.startswith("_"):
            continue
        if val is None:
            return False
    return True
