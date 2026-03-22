"""Validate marketing description quality and length."""

from agent_actions import udf_tool

MIN_DESCRIPTION_WORDS = 100
MAX_DESCRIPTION_WORDS = 300
MIN_BENEFITS = 3
MAX_BENEFITS = 7


@udf_tool()
def validate_description(data: dict) -> dict:
    """Validate marketing description meets quality standards."""
    description = data.get("marketing_description", "")
    hook = data.get("hook_sentence", "")
    benefits = data.get("key_benefits", [])
    audience = data.get("target_audience", "")

    issues = []

    # Check description length
    word_count = len(description.split()) if description else 0
    if word_count < MIN_DESCRIPTION_WORDS:
        issues.append(f"Description too short: {word_count} words (min: {MIN_DESCRIPTION_WORDS})")
    elif word_count > MAX_DESCRIPTION_WORDS:
        issues.append(f"Description too long: {word_count} words (max: {MAX_DESCRIPTION_WORDS})")

    # Check hook sentence
    if not hook:
        issues.append("Missing hook sentence")
    elif len(hook.split()) > 30:
        issues.append("Hook sentence too long (max 30 words)")

    # Check benefits
    benefit_count = len(benefits) if benefits else 0
    if benefit_count < MIN_BENEFITS:
        issues.append(f"Too few benefits: {benefit_count} (min: {MIN_BENEFITS})")
    elif benefit_count > MAX_BENEFITS:
        issues.append(f"Too many benefits: {benefit_count} (max: {MAX_BENEFITS})")

    # Check for empty benefits
    empty_benefits = sum(1 for b in benefits if not b or len(b.strip()) < 10)
    if empty_benefits > 0:
        issues.append(f"{empty_benefits} benefits are too short or empty")

    # Check target audience
    if not audience:
        issues.append("Missing target audience")
    elif len(audience.split()) < 5:
        issues.append("Target audience description too brief")

    # Check for placeholder text
    placeholder_phrases = ["lorem ipsum", "tbd", "to be determined", "[insert", "example"]
    description_lower = description.lower()
    for phrase in placeholder_phrases:
        if phrase in description_lower:
            issues.append(f"Contains placeholder text: '{phrase}'")

    return {
        "description_valid": len(issues) == 0,
        "word_count": word_count,
        "benefit_count": benefit_count,
        "validation_issues": issues,
    }
