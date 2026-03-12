"""DLP regex scanner for known prompt injection patterns.

Scans input prompts against a categorized database of regex patterns
that match common prompt injection techniques: role hijacking,
data exfiltration, instruction override, encoding evasion, and
delimiter injection.
"""

import re
from typing import Any, TypedDict

from agent_actions import udf_tool


class ScanDlpRegexInput(TypedDict, total=False):
    """Input schema for scan_dlp_regex."""

    prompt_text: str
    attack_patterns: dict[str, Any]


class ScanDlpRegexOutput(TypedDict, total=False):
    """Output schema for scan_dlp_regex."""

    matched_patterns: list[dict[str, str]]
    category_scores: dict[str, float]
    dlp_risk_score: float
    highest_category: str


# Default category weights if seed data unavailable
DEFAULT_CATEGORY_WEIGHTS = {
    "role_hijacking": 0.90,
    "data_exfiltration": 0.85,
    "instruction_override": 0.95,
    "encoding_evasion": 0.70,
    "delimiter_injection": 0.88,
}


@udf_tool()
def scan_dlp_regex(data: dict) -> dict:
    """Scan prompt text against known injection regex patterns.

    Matches the prompt against categorized patterns from seed data.
    Each category is scored based on the number and weight of matches.

    Args:
        data: Input containing prompt_text and attack_patterns seed data.

    Returns:
        Dict with matched_patterns, category_scores, dlp_risk_score,
        and highest_category.
    """
    content = data.get("content", data)
    prompt_text = content.get("prompt_text", "")
    prompt_lower = prompt_text.lower()

    # Load patterns from seed data or use empty fallback
    seed_patterns = content.get("attack_patterns", {})
    patterns_db = seed_patterns.get("patterns", {})
    category_weights = seed_patterns.get("category_weights", DEFAULT_CATEGORY_WEIGHTS)

    matched_patterns: list[dict[str, str]] = []
    category_scores: dict[str, float] = {}

    for category, patterns in patterns_db.items():
        match_count = 0
        for pattern in patterns:
            try:
                matches = re.findall(pattern, prompt_lower, re.IGNORECASE)
                if matches:
                    match_count += len(matches)
                    matched_patterns.append(
                        {
                            "category": category,
                            "pattern": pattern,
                            "match_count": len(matches),
                            "sample_match": str(matches[0])[:100],
                        }
                    )
            except re.error:
                # Skip invalid patterns gracefully
                continue

        # Score: sigmoid-like scaling based on match count and category weight
        weight = category_weights.get(category, 0.5)
        if match_count == 0:
            category_scores[category] = 0.0
        else:
            # Saturating score: more matches → higher score, capped at weight
            raw = min(match_count / 3.0, 1.0)
            category_scores[category] = round(raw * weight, 4)

    # Composite DLP risk score: max category score (worst signal dominates)
    if category_scores:
        dlp_risk_score = max(category_scores.values())
    else:
        dlp_risk_score = 0.0

    # Find highest-scoring category
    highest_category = "none"
    if category_scores:
        highest_category = max(category_scores, key=category_scores.get)
        if category_scores[highest_category] == 0.0:
            highest_category = "none"

    return {
        "matched_patterns": matched_patterns,
        "category_scores": category_scores,
        "dlp_risk_score": round(dlp_risk_score, 4),
        "highest_category": highest_category,
    }
