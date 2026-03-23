"""
Calculate weighted composite score from parallel assessment dimensions.
Demonstrates the fan-in pattern: three independent assessments merge into one score.
"""

from typing import Any

from agent_actions import udf_tool

# Default weights if seed data is unavailable
DEFAULT_WEIGHTS = {
    "skills": 0.40,
    "experience": 0.35,
    "culture_fit": 0.25,
}

TIER_THRESHOLDS = {
    "strong_hire": 8.0,
    "hire": 6.0,
    "borderline": 4.5,
}


@udf_tool()
def calculate_composite_score(data: dict[str, Any]) -> dict[str, Any]:
    """
    Calculate weighted composite score from skills, experience, and culture assessments.

    Pattern: Fan-in from 3 parallel branches with weighted aggregation.
    Returns: Dict with composite score, breakdown, and recommendation tier.
    """
    content = data.get("content", data)

    # Extract scores from each assessment dimension
    skills_data = content.get("assess_skills", {})
    experience_data = content.get("assess_experience", {})
    culture_data = content.get("assess_culture_fit", {})

    skills_score = _extract_score(skills_data, "skills_score")
    experience_score = _extract_score(experience_data, "experience_score")
    culture_score = _extract_score(culture_data, "culture_score")

    # Get weights from seed data or use defaults
    role_requirements = content.get("role_requirements", {})
    weights = role_requirements.get("scoring_weights", DEFAULT_WEIGHTS)

    skills_weight = weights.get("skills", DEFAULT_WEIGHTS["skills"])
    experience_weight = weights.get("experience", DEFAULT_WEIGHTS["experience"])
    culture_weight = weights.get("culture_fit", DEFAULT_WEIGHTS["culture_fit"])

    # Calculate weighted components
    skills_weighted = round(skills_score * skills_weight, 2)
    experience_weighted = round(experience_score * experience_weight, 2)
    culture_weighted = round(culture_score * culture_weight, 2)

    # Composite score
    composite_score = round(skills_weighted + experience_weighted + culture_weighted, 2)

    # Determine recommendation tier
    if composite_score >= TIER_THRESHOLDS["strong_hire"]:
        tier = "strong_hire"
    elif composite_score >= TIER_THRESHOLDS["hire"]:
        tier = "hire"
    elif composite_score >= TIER_THRESHOLDS["borderline"]:
        tier = "borderline"
    else:
        tier = "no_hire"

    # Pass through key details from assessments for the recommendation step
    return {
        "skills_score": skills_score,
        "experience_score": experience_score,
        "culture_score": culture_score,
        "composite_score": composite_score,
        "score_breakdown": {
            "skills_weighted": skills_weighted,
            "experience_weighted": experience_weighted,
            "culture_weighted": culture_weighted,
        },
        "weights_used": {
            "skills": skills_weight,
            "experience": experience_weight,
            "culture_fit": culture_weight,
        },
        "recommendation_tier": tier,
        # Forward assessment details for the recommendation prompt
        "skill_gaps": skills_data.get("skill_gaps", []),
        "skill_strengths": skills_data.get("skill_strengths", []),
        "skills_reasoning": skills_data.get("skills_reasoning", ""),
        "seniority_match": experience_data.get("seniority_match", "unknown"),
        "role_progression": experience_data.get("role_progression", "unknown"),
        "experience_reasoning": experience_data.get("experience_reasoning", ""),
        "communication_quality": culture_data.get("communication_quality", "unknown"),
        "culture_risks": culture_data.get("culture_risks", []),
        "culture_reasoning": culture_data.get("culture_reasoning", ""),
    }


def _extract_score(data: dict[str, Any], key: str) -> float:
    """Extract a numeric score from assessment data, with fallback."""
    if isinstance(data, dict):
        score = data.get(key, 5.0)
        try:
            return float(score)
        except (TypeError, ValueError):
            return 5.0
    return 5.0
