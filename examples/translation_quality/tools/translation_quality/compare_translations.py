"""Compare three parallel translation strategies and select the best candidate.

Scores each translation by completeness (sentence coverage) and
self-reported confidence, then picks the highest-scoring candidate.
Deterministic — no LLM needed.
"""

from typing import Any

from agent_actions import udf_tool

# Strategy labels mapped to version indices
STRATEGY_LABELS = {
    1: "literal",
    2: "idiomatic",
    3: "domain_adapted",
}


def _count_sentences(text: str) -> int:
    """Rough sentence count by splitting on sentence-ending punctuation."""
    if not text:
        return 0
    # Handle common sentence terminators across languages
    count = 0
    for char in text:
        if char in ".!?\u3002\uff01\uff1f":  # Include CJK sentence endings
            count += 1
    return max(count, 1)  # At least 1 sentence if text exists


def _score_translation(
    translation_data: dict[str, Any],
    source_sentence_count: int,
) -> dict[str, float]:
    """Score a single translation on completeness and confidence."""
    translated_text = translation_data.get("translated_text", "")
    confidence = translation_data.get("confidence", 5)

    # Completeness: ratio of translated sentences to source sentences
    translated_sentences = _count_sentences(translated_text)
    if source_sentence_count > 0:
        completeness_ratio = min(translated_sentences / source_sentence_count, 1.5)
    else:
        completeness_ratio = 1.0

    # Penalize if too few sentences (likely omissions)
    # Slight penalty if too many (likely additions/splits)
    if completeness_ratio < 0.8:
        completeness_score = completeness_ratio * 8  # Heavy penalty for omissions
    elif completeness_ratio > 1.2:
        completeness_score = 8 - (completeness_ratio - 1.2) * 2  # Mild penalty
    else:
        completeness_score = 8 + (1.0 - abs(1.0 - completeness_ratio)) * 2

    completeness_score = max(0, min(10, completeness_score))

    # Confidence: use as-is (already 1-10)
    confidence_score = max(1, min(10, confidence))

    # Weighted total: completeness matters more than self-reported confidence
    total = round(completeness_score * 0.6 + confidence_score * 0.4, 2)

    return {
        "completeness": round(completeness_score, 2),
        "confidence": confidence_score,
        "total": total,
    }


@udf_tool()
def compare_translations(data: dict[str, Any]) -> dict[str, Any]:
    """Compare 3 parallel translation strategies and select the best.

    Accesses versioned outputs: translate_1, translate_2, translate_3.
    Returns best translation, scores, and selection reasoning.
    """
    content = data.get("content", data)

    # Get source text for sentence counting
    source_text = content.get("text", content.get("source", {}).get("text", ""))
    source_sentence_count = _count_sentences(source_text)

    # Collect and score all translations
    candidates = {}
    scores = {}
    all_translations = {}

    for version_id, strategy in STRATEGY_LABELS.items():
        key = f"translate_{version_id}"
        translation_data = content.get(key, {})

        if not isinstance(translation_data, dict):
            continue

        score = _score_translation(translation_data, source_sentence_count)
        candidates[strategy] = {
            "text": translation_data.get("translated_text", ""),
            "score": score,
            "confidence": translation_data.get("confidence", 5),
            "notes": translation_data.get("notes", []),
            "term_handling": translation_data.get("term_handling", []),
        }
        scores[strategy] = score
        all_translations[strategy] = translation_data.get("translated_text", "")

    if not candidates:
        return {
            "best_translation": "",
            "selected_strategy": "none",
            "selection_reasoning": "No translations were produced",
            "scores": {},
            "all_translations": {},
        }

    # Select the best by total score
    best_strategy = max(scores, key=lambda s: scores[s]["total"])
    best_candidate = candidates[best_strategy]

    # Build reasoning
    score_summary = []
    for strategy, score in sorted(scores.items(), key=lambda x: -x[1]["total"]):
        score_summary.append(
            f"{strategy}: total={score['total']}, "
            f"completeness={score['completeness']}, "
            f"confidence={score['confidence']}"
        )

    reasoning_parts = [
        f"Selected '{best_strategy}' strategy with highest total score "
        f"({scores[best_strategy]['total']}).",
    ]
    if len(scores) > 1:
        runner_up = sorted(scores.items(), key=lambda x: -x[1]["total"])[1]
        gap = round(scores[best_strategy]["total"] - runner_up[1]["total"], 2)
        if gap < 0.5:
            reasoning_parts.append(
                f"Close margin ({gap} pts) over '{runner_up[0]}' — "
                f"both were strong candidates."
            )
        else:
            reasoning_parts.append(
                f"Clear winner by {gap} pts over '{runner_up[0]}'."
            )

    reasoning_parts.append(f"Score breakdown: {'; '.join(score_summary)}")

    return {
        "best_translation": best_candidate["text"],
        "selected_strategy": best_strategy,
        "selection_reasoning": " ".join(reasoning_parts),
        "scores": scores,
        "all_translations": all_translations,
    }
