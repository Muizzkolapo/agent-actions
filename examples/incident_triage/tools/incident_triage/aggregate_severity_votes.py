"""
Aggregate severity classifications from multiple independent classifiers.
Demonstrates weighted consensus pattern with confidence scoring.
"""

from typing import Any

from agent_actions import udf_tool

SEVERITY_WEIGHTS = {
    "SEV1": 5,  # Critical
    "SEV2": 4,  # High
    "SEV3": 3,  # Medium
    "SEV4": 2,  # Low
    "SEV5": 1,  # Informational
}


@udf_tool()
def aggregate_severity_votes(data: dict[str, Any]) -> dict[str, Any]:
    """
    Aggregate severity classifications using weighted voting with confidence.

    Pattern: Version consumption with merge pattern
    Returns: Dict (not list) when using passthrough
    """
    content = data.get("content", data)

    # Collect votes from all classifiers
    votes = []
    for i in range(1, 4):
        classifier_key = f"classify_severity_{i}"
        classifier_data = content.get(classifier_key, {})

        if isinstance(classifier_data, dict):
            severity = classifier_data.get("severity", "SEV5")
            confidence = classifier_data.get("confidence", 0.5)
            reasoning = classifier_data.get("reasoning", "")

            votes.append(
                {
                    "severity": severity,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "weight": SEVERITY_WEIGHTS.get(severity, 1),
                }
            )

    if not votes:
        return {
            "final_severity": "SEV5",
            "confidence_score": 0.0,
            "consensus_method": "default",
            "vote_summary": "No votes received",
        }

    # Weighted voting: higher severity weighted by confidence
    weighted_scores = {}
    for vote in votes:
        sev = vote["severity"]
        # Weight = severity_weight * confidence
        score = vote["weight"] * vote["confidence"]
        weighted_scores[sev] = weighted_scores.get(sev, 0) + score

    # Select severity with highest weighted score
    final_severity = max(weighted_scores.items(), key=lambda x: x[1])[0]

    # Calculate consensus confidence
    matching_votes = [v for v in votes if v["severity"] == final_severity]
    avg_confidence = sum(v["confidence"] for v in matching_votes) / len(matching_votes)

    # Check for split decision
    unique_severities = len(set(v["severity"] for v in votes))
    is_split = unique_severities == len(votes)

    # Compile reasoning from all votes
    all_reasoning = [f"{v['severity']} ({v['confidence']:.2f}): {v['reasoning']}" for v in votes]

    return {
        "final_severity": final_severity,
        "confidence_score": round(avg_confidence, 3),
        "consensus_method": "weighted_voting",
        "is_split_decision": is_split,
        "vote_summary": "\n".join(all_reasoning),
        "severity_distribution": {
            v["severity"]: sum(1 for vote in votes if vote["severity"] == v["severity"])
            for v in votes
        },
    }
