"""Aggregate detection scores from all four statistical layers.

Collects results from scan_dlp_regex, score_pfd_embedding, score_topic_jsd,
and score_bayesian_elbo, then computes a weighted aggregate score and
a statistical verdict.
"""

from typing import Any, TypedDict

from agent_actions import udf_tool


class AggregateDetectionScoresInput(TypedDict, total=False):
    """Input schema for aggregate_detection_scores."""

    scan_dlp_regex: dict[str, Any]
    score_pfd_embedding: dict[str, Any]
    score_topic_jsd: dict[str, Any]
    score_bayesian_elbo: dict[str, Any]


class AggregateDetectionScoresOutput(TypedDict, total=False):
    """Output schema for aggregate_detection_scores."""

    layer_scores: dict[str, float]
    aggregate_score: float
    unanimous_safe: bool
    unanimous_risky: bool
    statistical_verdict: str


# Layer weights for weighted aggregate
LAYER_WEIGHTS = {
    "dlp": 0.30,
    "pfd": 0.25,
    "jsd": 0.20,
    "elbo": 0.25,
}

# Thresholds for classification
SAFE_THRESHOLD = 0.20
RISKY_THRESHOLD = 0.55


@udf_tool()
def aggregate_detection_scores(data: dict) -> dict:
    """Aggregate scores from all four statistical detection layers.

    Computes a weighted aggregate score and determines a statistical
    verdict (SAFE, SUSPICIOUS, or RISKY) based on configurable thresholds.

    Args:
        data: Input containing results from all four upstream detection layers.

    Returns:
        Dict with layer_scores, aggregate_score, unanimous flags, and
        statistical_verdict.
    """
    content = data.get("content", data)

    # Extract scores from each layer
    dlp_data = content.get("scan_dlp_regex", {})
    pfd_data = content.get("score_pfd_embedding", {})
    jsd_data = content.get("score_topic_jsd", {})
    elbo_data = content.get("score_bayesian_elbo", {})

    dlp_score = dlp_data.get("dlp_risk_score", 0.0)
    pfd_score = pfd_data.get("pfd_composite", 0.0)
    jsd_score = jsd_data.get("jsd_score", 0.0)
    elbo_score = elbo_data.get("elbo_score", 0.0)

    layer_scores = {
        "dlp": round(dlp_score, 4),
        "pfd": round(pfd_score, 4),
        "jsd": round(jsd_score, 4),
        "elbo": round(elbo_score, 4),
    }

    # Weighted aggregate
    aggregate_score = (
        LAYER_WEIGHTS["dlp"] * dlp_score
        + LAYER_WEIGHTS["pfd"] * pfd_score
        + LAYER_WEIGHTS["jsd"] * jsd_score
        + LAYER_WEIGHTS["elbo"] * elbo_score
    )
    aggregate_score = round(min(aggregate_score, 1.0), 4)

    # Unanimity checks
    all_scores = [dlp_score, pfd_score, jsd_score, elbo_score]
    unanimous_safe = all(s < SAFE_THRESHOLD for s in all_scores)
    unanimous_risky = all(s > RISKY_THRESHOLD for s in all_scores)

    # Statistical verdict
    if aggregate_score >= RISKY_THRESHOLD:
        statistical_verdict = "RISKY"
    elif aggregate_score <= SAFE_THRESHOLD:
        statistical_verdict = "SAFE"
    else:
        statistical_verdict = "SUSPICIOUS"

    return {
        "layer_scores": layer_scores,
        "aggregate_score": aggregate_score,
        "unanimous_safe": unanimous_safe,
        "unanimous_risky": unanimous_risky,
        "statistical_verdict": statistical_verdict,
    }
