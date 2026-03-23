"""
Aggregate topic classification votes from multiple independent classifiers.
Uses majority rule to determine consensus category with confidence tracking.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def aggregate_topic_votes(data: dict[str, Any]) -> dict[str, Any]:
    """
    Aggregate three independent topic classification votes using majority rule.

    Reads classify_topic_1, classify_topic_2, classify_topic_3 from content,
    each containing assigned_category, confidence, and reasoning.

    Returns the majority category. On a 3-way split, picks the vote with
    the highest confidence.

    Output fields:
        - consensus_category: The winning category
        - vote_agreement: Fraction of votes that agreed (0.33, 0.67, or 1.0)
        - is_unanimous: Whether all three classifiers agreed
        - vote_summary: Human-readable breakdown of all votes
    """
    content = data.get("content", data)

    # Collect votes from all three classifiers
    votes: list[dict[str, Any]] = []
    for i in range(1, 4):
        classifier_key = f"classify_topic_{i}"
        classifier_data = content.get(classifier_key, {})

        if isinstance(classifier_data, dict):
            votes.append(
                {
                    "assigned_category": classifier_data.get(
                        "assigned_category", "unknown"
                    ),
                    "confidence": classifier_data.get("confidence", 0.0),
                    "reasoning": classifier_data.get("reasoning", ""),
                }
            )

    if not votes:
        return {
            "consensus_category": "unknown",
            "vote_agreement": 0.0,
            "is_unanimous": False,
            "vote_summary": "No classification votes received",
        }

    # Count occurrences of each category
    category_counts: dict[str, int] = {}
    for vote in votes:
        cat = vote["assigned_category"]
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Find the majority category
    max_count = max(category_counts.values())
    majority_candidates = [
        cat for cat, count in category_counts.items() if count == max_count
    ]

    if len(majority_candidates) == 1:
        # Clear majority (2-of-3 or 3-of-3)
        consensus_category = majority_candidates[0]
    else:
        # 3-way split (each category appears once) -- pick highest confidence
        consensus_category = max(
            votes, key=lambda v: v["confidence"]
        )["assigned_category"]

    # Calculate agreement fraction
    agreement_count = category_counts.get(consensus_category, 0)
    vote_agreement = round(agreement_count / len(votes), 2)

    is_unanimous = agreement_count == len(votes)

    # Build human-readable vote summary
    vote_lines = [
        f"Classifier {i + 1}: {v['assigned_category']} "
        f"(confidence={v['confidence']:.2f}) — {v['reasoning']}"
        for i, v in enumerate(votes)
    ]

    return {
        "consensus_category": consensus_category,
        "vote_agreement": vote_agreement,
        "is_unanimous": is_unanimous,
        "vote_summary": "\n".join(vote_lines),
    }
