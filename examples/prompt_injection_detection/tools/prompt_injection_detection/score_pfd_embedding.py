"""Prompt Frechet Distance scoring via structural/statistical proxy.

Computes a structural anomaly score without external ML dependencies
by analyzing character entropy, instruction density, structural anomalies,
and question density against baseline corpus statistics.
"""

import math
import re
from typing import Any, TypedDict

from agent_actions import udf_tool


class ScorePfdEmbeddingInput(TypedDict, total=False):
    """Input schema for score_pfd_embedding."""

    prompt_text: str
    legitimate_corpus_stats: dict[str, Any]


class ScorePfdEmbeddingOutput(TypedDict, total=False):
    """Output schema for score_pfd_embedding."""

    entropy_score: float
    instruction_density: float
    structural_anomaly: float
    question_density: float
    pfd_composite: float
    anomaly_flags: list[str]


def _character_entropy(text: str) -> float:
    """Compute Shannon entropy over character frequencies."""
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    for ch in text:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(text)
    entropy = 0.0
    for count in freq.values():
        p = count / length
        if p > 0:
            entropy -= p * math.log2(p)
    return round(entropy, 4)


def _instruction_density(text: str, imperative_verbs: list[str]) -> float:
    """Compute ratio of imperative verbs to total tokens."""
    tokens = re.findall(r"\b\w+\b", text.lower())
    if not tokens:
        return 0.0
    imperative_set = set(v.lower() for v in imperative_verbs)
    imperative_count = sum(1 for t in tokens if t in imperative_set)
    return round(imperative_count / len(tokens), 4)


def _structural_anomaly(text: str, baseline_stats: dict[str, Any]) -> float:
    """Compute structural anomaly based on special chars and line length."""
    if not text:
        return 0.0

    # Special character ratio
    special_chars = sum(1 for c in text if not c.isalnum() and not c.isspace())
    special_ratio = special_chars / max(len(text), 1)
    ref_special_mean = baseline_stats.get("special_char_ratio", {}).get("mean", 0.04)
    ref_special_std = baseline_stats.get("special_char_ratio", {}).get("std", 0.03)
    special_z = abs(special_ratio - ref_special_mean) / max(ref_special_std, 0.001)

    # Average line length deviation
    lines = text.split("\n")
    avg_line_len = sum(len(line) for line in lines) / max(len(lines), 1)
    ref_line_mean = baseline_stats.get("avg_line_length", {}).get("mean", 62.5)
    ref_line_std = baseline_stats.get("avg_line_length", {}).get("std", 28.0)
    line_z = abs(avg_line_len - ref_line_mean) / max(ref_line_std, 0.001)

    # Combined anomaly: average of z-scores, normalized to 0-1 range
    combined_z = (special_z + line_z) / 2.0
    anomaly = min(combined_z / 3.0, 1.0)  # 3 sigma → score of 1.0
    return round(anomaly, 4)


def _question_density(text: str) -> float:
    """Compute ratio of question marks to sentence count."""
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return 0.0
    question_count = text.count("?")
    return round(question_count / len(sentences), 4)


@udf_tool()
def score_pfd_embedding(data: dict) -> dict:
    """Compute Prompt Frechet Distance via structural/statistical proxy.

    Analyzes character entropy, instruction density, structural anomalies,
    and question patterns to detect unusual prompt structure without
    requiring ML embeddings.

    Args:
        data: Input containing prompt_text and legitimate_corpus_stats seed data.

    Returns:
        Dict with individual scores, composite PFD score, and anomaly flags.
    """
    content = data.get("content", data)
    prompt_text = content.get("prompt_text", "")
    corpus_stats = content.get("legitimate_corpus_stats", {})

    # All imperative verbs (including suspicious ones)
    all_imperatives = corpus_stats.get(
        "imperative_verbs",
        [
            "ignore",
            "forget",
            "disregard",
            "override",
            "pretend",
            "act",
            "explain",
            "describe",
            "summarize",
            "help",
            "write",
            "generate",
        ],
    )
    benign_imperatives = set(
        corpus_stats.get(
            "benign_imperative_verbs",
            [
                "explain",
                "describe",
                "summarize",
                "help",
                "write",
                "generate",
            ],
        )
    )

    structural_baseline = corpus_stats.get("structural_metrics", {})

    # Compute individual scores
    entropy = _character_entropy(prompt_text)
    instr_density = _instruction_density(prompt_text, all_imperatives)
    struct_anomaly = _structural_anomaly(prompt_text, structural_baseline)
    q_density = _question_density(prompt_text)

    # Entropy anomaly: deviation from baseline
    entropy_mean = corpus_stats.get("character_entropy", {}).get("mean", 4.18)
    entropy_std = corpus_stats.get("character_entropy", {}).get("std", 0.42)
    entropy_z = abs(entropy - entropy_mean) / max(entropy_std, 0.001)
    entropy_score = min(entropy_z / 3.0, 1.0)

    # Instruction density anomaly: compare against baseline
    instr_mean = corpus_stats.get("instruction_density", {}).get("mean", 0.08)
    instr_std = corpus_stats.get("instruction_density", {}).get("std", 0.05)
    instr_z = max(instr_density - instr_mean, 0) / max(instr_std, 0.001)
    instr_score = min(instr_z / 3.0, 1.0)

    # Suspicious imperative ratio: what fraction of imperatives are non-benign?
    tokens = re.findall(r"\b\w+\b", prompt_text.lower())
    imperative_set = set(v.lower() for v in all_imperatives)
    found_imperatives = [t for t in tokens if t in imperative_set]
    suspicious_imperatives = [t for t in found_imperatives if t not in benign_imperatives]
    suspicious_ratio = len(suspicious_imperatives) / max(len(found_imperatives), 1)

    # Boost instruction density score if suspicious verbs dominate
    if suspicious_ratio > 0.5 and len(suspicious_imperatives) >= 2:
        instr_score = min(instr_score + 0.3, 1.0)

    # Composite PFD score: weighted combination
    pfd_composite = (
        0.25 * entropy_score + 0.35 * instr_score + 0.25 * struct_anomaly + 0.15 * q_density
    )
    pfd_composite = round(min(pfd_composite, 1.0), 4)

    # Anomaly flags
    anomaly_flags = []
    if entropy_score > 0.6:
        anomaly_flags.append("high_entropy_deviation")
    if instr_score > 0.5:
        anomaly_flags.append("high_instruction_density")
    if struct_anomaly > 0.5:
        anomaly_flags.append("structural_anomaly_detected")
    if suspicious_ratio > 0.5 and len(suspicious_imperatives) >= 2:
        anomaly_flags.append(f"suspicious_imperatives:{','.join(suspicious_imperatives[:5])}")
    if q_density > 0.5:
        anomaly_flags.append("high_question_density")

    return {
        "entropy_score": round(entropy_score, 4),
        "instruction_density": round(instr_score, 4),
        "structural_anomaly": round(struct_anomaly, 4),
        "question_density": round(q_density, 4),
        "pfd_composite": pfd_composite,
        "anomaly_flags": anomaly_flags,
    }
