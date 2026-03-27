"""Topic distribution analysis with Jensen-Shannon Divergence.

Computes a keyword-based topic distribution over the prompt and measures
its divergence from a reference distribution of legitimate prompts.
High divergence toward system_control or data_extraction topics signals
potential injection.
"""

import math
import re
from typing import Any, TypedDict

from agent_actions import udf_tool


class ScoreTopicJsdInput(TypedDict, total=False):
    """Input schema for score_topic_jsd."""

    prompt_text: str
    topic_reference_distribution: dict[str, Any]


class ScoreTopicJsdOutput(TypedDict, total=False):
    """Output schema for score_topic_jsd."""

    detected_topics: dict[str, float]
    jsd_score: float
    dominant_topic: str
    topic_anomaly_flags: list[str]


def _compute_topic_distribution(
    text: str, topic_keywords: dict[str, list[str]]
) -> dict[str, float]:
    """Compute topic distribution based on keyword frequency."""
    tokens = set(re.findall(r"\b\w+\b", text.lower()))
    topic_counts: dict[str, int] = {}
    total = 0

    for topic, keywords in topic_keywords.items():
        count = sum(1 for kw in keywords if kw.lower() in tokens)
        topic_counts[topic] = count
        total += count

    if total == 0:
        # Uniform distribution if no keywords match
        n = len(topic_keywords)
        return {topic: 1.0 / n for topic in topic_keywords}

    return {topic: count / total for topic, count in topic_counts.items()}


def _jensen_shannon_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Compute Jensen-Shannon Divergence between two distributions.

    JSD is symmetric and bounded [0, 1] when using log base 2.
    """
    all_keys = set(p.keys()) | set(q.keys())
    # Smoothing: add small epsilon to avoid log(0)
    eps = 1e-10

    jsd = 0.0
    for key in all_keys:
        p_val = p.get(key, 0.0) + eps
        q_val = q.get(key, 0.0) + eps
        m_val = (p_val + q_val) / 2.0

        if p_val > 0:
            jsd += 0.5 * p_val * math.log2(p_val / m_val)
        if q_val > 0:
            jsd += 0.5 * q_val * math.log2(q_val / m_val)

    return max(0.0, min(jsd, 1.0))


@udf_tool()
def score_topic_jsd(data: dict) -> dict:
    """Compute topic distribution and Jensen-Shannon Divergence.

    Builds a keyword-based topic distribution for the prompt and compares
    it to a reference distribution from legitimate corpus. Elevated
    system_control or data_extraction topics signal injection risk.

    Args:
        data: Input containing prompt_text and topic_reference_distribution seed data.

    Returns:
        Dict with detected_topics, jsd_score, dominant_topic, and
        topic_anomaly_flags.
    """
    content = data.get("content", data)
    prompt_text = content.get("prompt_text", "")
    ref_data = content.get("topic_reference_distribution", {})

    topic_keywords = ref_data.get("topic_keywords", {})
    reference_dist = ref_data.get("reference_distribution", {})
    thresholds = ref_data.get("anomaly_thresholds", {})

    # Compute topic distribution for this prompt
    detected_topics = _compute_topic_distribution(prompt_text, topic_keywords)

    # Round for readability
    detected_topics = {k: round(v, 4) for k, v in detected_topics.items()}

    # Compute JSD against reference distribution
    jsd_score = _jensen_shannon_divergence(detected_topics, reference_dist)
    jsd_score = round(jsd_score, 4)

    # Find dominant topic
    dominant_topic = max(detected_topics, key=detected_topics.get) if detected_topics else "unknown"

    # Anomaly flags
    topic_anomaly_flags = []

    sys_control_threshold = thresholds.get("system_control_elevated", 0.15)
    data_extract_threshold = thresholds.get("data_extraction_elevated", 0.10)
    jsd_suspicious = thresholds.get("jsd_suspicious", 0.25)
    jsd_high_risk = thresholds.get("jsd_high_risk", 0.45)

    if detected_topics.get("system_control", 0) > sys_control_threshold:
        topic_anomaly_flags.append("elevated_system_control_topic")

    if detected_topics.get("data_extraction", 0) > data_extract_threshold:
        topic_anomaly_flags.append("elevated_data_extraction_topic")

    if dominant_topic in ("system_control", "data_extraction"):
        topic_anomaly_flags.append(f"dominant_topic_is_{dominant_topic}")

    if jsd_score > jsd_high_risk:
        topic_anomaly_flags.append("high_jsd_divergence")
    elif jsd_score > jsd_suspicious:
        topic_anomaly_flags.append("moderate_jsd_divergence")

    return {
        "detected_topics": detected_topics,
        "jsd_score": jsd_score,
        "dominant_topic": dominant_topic,
        "topic_anomaly_flags": topic_anomaly_flags,
    }
