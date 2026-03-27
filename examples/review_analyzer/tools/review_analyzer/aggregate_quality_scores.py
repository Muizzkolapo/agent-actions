"""Aggregate quality scores from multiple independent review scorers.

Uses weighted consensus with configurable criteria weights from the
evaluation rubric seed data.
"""

from typing import Any

from agent_actions import udf_tool

# Criteria weights (must match seed_data/evaluation_rubric.json)
CRITERIA_WEIGHTS = {
    "helpfulness": 0.35,
    "specificity": 0.30,
    "authenticity": 0.35,
}


@udf_tool()
def aggregate_quality_scores(data: dict[str, Any]) -> dict[str, Any]:
    """Aggregate 3 independent quality scores into a weighted consensus.

    Accesses versioned outputs: score_quality_1, score_quality_2, score_quality_3.
    Returns consensus score, spread, and combined insights.
    """
    content = data.get("content", data)

    # Collect scores from all scorers
    scores = []
    all_reasoning = []
    all_red_flags = []

    for i in range(1, 4):
        scorer_key = f"score_quality_{i}"
        scorer_data = content.get(scorer_key, {})

        if not isinstance(scorer_data, dict):
            continue

        helpfulness = scorer_data.get("helpfulness_score", 5)
        specificity = scorer_data.get("specificity_score", 5)
        authenticity = scorer_data.get("authenticity_score", 5)

        # Weighted score per scorer
        weighted = (
            helpfulness * CRITERIA_WEIGHTS["helpfulness"]
            + specificity * CRITERIA_WEIGHTS["specificity"]
            + authenticity * CRITERIA_WEIGHTS["authenticity"]
        )

        scores.append(
            {
                "scorer_id": i,
                "helpfulness": helpfulness,
                "specificity": specificity,
                "authenticity": authenticity,
                "overall": round(weighted, 2),
                "reasoning": scorer_data.get("scoring_reasoning", ""),
            }
        )

        all_reasoning.append(
            f"Scorer {i} ({weighted:.1f}/10): {scorer_data.get('scoring_reasoning', 'No reasoning')}"
        )

        red_flags = scorer_data.get("red_flags", [])
        if red_flags:
            all_red_flags.extend(red_flags)

    if not scores:
        return {
            "consensus_score": 0,
            "score_spread": 0,
            "is_split_decision": False,
            "strengths": [],
            "weaknesses": [],
            "red_flags": [],
            "vote_summary": "No scores collected",
        }

    # Consensus: average of weighted scores
    overall_scores = [s["overall"] for s in scores]
    consensus_score = round(sum(overall_scores) / len(overall_scores), 1)
    score_spread = round(max(overall_scores) - min(overall_scores), 1)
    is_split = score_spread > 2.0

    # Identify consensus strengths/weaknesses by criteria
    avg_helpfulness = sum(s["helpfulness"] for s in scores) / len(scores)
    avg_specificity = sum(s["specificity"] for s in scores) / len(scores)
    avg_authenticity = sum(s["authenticity"] for s in scores) / len(scores)

    strengths = []
    weaknesses = []

    criteria_avgs = {
        "Helpfulness": avg_helpfulness,
        "Specificity": avg_specificity,
        "Authenticity": avg_authenticity,
    }

    for name, avg in criteria_avgs.items():
        if avg >= 7:
            strengths.append(f"{name} ({avg:.1f}/10)")
        elif avg < 5:
            weaknesses.append(f"{name} ({avg:.1f}/10)")

    # Deduplicate red flags
    unique_red_flags = list(set(all_red_flags))

    return {
        "consensus_score": consensus_score,
        "score_spread": score_spread,
        "is_split_decision": is_split,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "red_flags": unique_red_flags,
        "vote_summary": "\n".join(all_reasoning),
    }
