"""Bayesian anomaly scoring via pseudo-ELBO computation.

Computes a Bayesian-inspired anomaly score using bigram novelty,
length anomaly (z-score), repetition score, and vocabulary surprise.
These are combined into a pseudo Evidence Lower Bound (ELBO) that
indicates how unexpected the prompt is relative to the baseline corpus.
"""

import re
from typing import Any, TypedDict

from agent_actions import udf_tool


class ScoreBayesianElboInput(TypedDict, total=False):
    """Input schema for score_bayesian_elbo."""

    prompt_text: str
    legitimate_corpus_stats: dict[str, Any]


class ScoreBayesianElboOutput(TypedDict, total=False):
    """Output schema for score_bayesian_elbo."""

    bigram_novelty: float
    length_anomaly: float
    repetition_score: float
    vocab_surprise: float
    elbo_score: float
    anomaly_flags: list[str]


def _bigram_novelty(
    tokens: list[str], baseline_novelty_mean: float, baseline_novelty_std: float
) -> float:
    """Compute bigram novelty score.

    Measures the fraction of unique bigrams (consecutive token pairs),
    which indicates how structurally unusual the text is.
    """
    if len(tokens) < 2:
        return 0.0

    bigrams = set()
    for i in range(len(tokens) - 1):
        bigrams.add((tokens[i], tokens[i + 1]))

    total_bigrams = len(tokens) - 1
    novelty_rate = len(bigrams) / total_bigrams

    # Z-score against baseline
    z = (novelty_rate - baseline_novelty_mean) / max(baseline_novelty_std, 0.001)
    # Normalize: positive z means more novel than expected
    return round(min(max(z, 0) / 3.0, 1.0), 4)


def _length_anomaly(text: str, mean_chars: float, std_chars: float) -> float:
    """Compute length anomaly as z-score of character count."""
    length = len(text)
    z = abs(length - mean_chars) / max(std_chars, 1)
    return round(min(z / 3.0, 1.0), 4)


def _repetition_score(tokens: list[str], n: int = 3) -> float:
    """Compute fraction of repeated n-grams."""
    if len(tokens) < n:
        return 0.0

    ngrams = []
    for i in range(len(tokens) - n + 1):
        ngrams.append(tuple(tokens[i : i + n]))

    total = len(ngrams)
    unique = len(set(ngrams))
    repeated_fraction = 1.0 - (unique / total) if total > 0 else 0.0
    return round(repeated_fraction, 4)


def _vocabulary_surprise(
    tokens: list[str], baseline_unique_mean: float, baseline_unique_std: float
) -> float:
    """Compute vocabulary surprise based on unique token ratio deviation."""
    if not tokens:
        return 0.0

    unique_ratio = len(set(tokens)) / len(tokens)
    # Low unique ratio (lots of repetition) or very high ratio can be surprising
    z = abs(unique_ratio - baseline_unique_mean) / max(baseline_unique_std, 0.001)
    return round(min(z / 3.0, 1.0), 4)


@udf_tool()
def score_bayesian_elbo(data: dict) -> dict:
    """Compute Bayesian anomaly score via pseudo-ELBO.

    Combines bigram novelty, length anomaly, repetition score, and
    vocabulary surprise into a composite anomaly score that indicates
    how statistically unusual the prompt is relative to legitimate
    corpus baselines.

    Args:
        data: Input containing prompt_text and legitimate_corpus_stats seed data.

    Returns:
        Dict with individual component scores, composite elbo_score,
        and anomaly_flags.
    """
    content = data.get("content", data)
    prompt_text = content.get("prompt_text", "")
    corpus_stats = content.get("legitimate_corpus_stats", {})

    # Tokenize
    tokens = re.findall(r"\b\w+\b", prompt_text.lower())

    # Baseline stats
    bigram_stats = corpus_stats.get("bigram_stats", {})
    length_stats = corpus_stats.get("length_stats", {})
    vocab_stats = corpus_stats.get("vocabulary_stats", {})
    rep_stats = corpus_stats.get("repetition_stats", {})

    # Compute individual components
    b_novelty = _bigram_novelty(
        tokens,
        bigram_stats.get("mean_novelty_rate", 0.35),
        bigram_stats.get("std_novelty_rate", 0.12),
    )

    l_anomaly = _length_anomaly(
        prompt_text,
        length_stats.get("mean_chars", 285),
        length_stats.get("std_chars", 180),
    )

    r_score = _repetition_score(tokens, n=3)

    # Repetition anomaly: compare against baseline
    rep_mean = rep_stats.get("mean_score", 0.05)
    rep_std = rep_stats.get("std_score", 0.04)
    rep_z = max(r_score - rep_mean, 0) / max(rep_std, 0.001)
    rep_anomaly = round(min(rep_z / 3.0, 1.0), 4)

    v_surprise = _vocabulary_surprise(
        tokens,
        vocab_stats.get("mean_unique_ratio", 0.72),
        vocab_stats.get("std_unique_ratio", 0.10),
    )

    # Pseudo-ELBO: higher = more anomalous
    elbo_score = 0.30 * b_novelty + 0.25 * l_anomaly + 0.20 * rep_anomaly + 0.25 * v_surprise
    elbo_score = round(min(elbo_score, 1.0), 4)

    # Anomaly flags
    anomaly_flags = []
    if b_novelty > 0.5:
        anomaly_flags.append("high_bigram_novelty")
    if l_anomaly > 0.5:
        anomaly_flags.append("unusual_length")
    if rep_anomaly > 0.5:
        anomaly_flags.append("high_repetition")
    if v_surprise > 0.5:
        anomaly_flags.append("vocabulary_surprise")
    if elbo_score > 0.6:
        anomaly_flags.append("high_overall_anomaly")

    return {
        "bigram_novelty": b_novelty,
        "length_anomaly": l_anomaly,
        "repetition_score": round(r_score, 4),
        "vocab_surprise": v_surprise,
        "elbo_score": elbo_score,
        "anomaly_flags": anomaly_flags,
    }
