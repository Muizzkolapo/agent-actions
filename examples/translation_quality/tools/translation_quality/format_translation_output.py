"""Format the final translation output with quality metadata.

Fan-in tool that packages the selected translation, back-translation
validation results, and quality assessment into the final structure.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def format_translation_output(data: dict[str, Any]) -> dict[str, Any]:
    """Package final translation with quality metadata and validation results.

    Combines outputs from:
    - extract_context (domain analysis, key terms)
    - select_best_translation (winning translation + strategy)
    - back_translate (round-trip text)
    - validate_quality (quality score, drift analysis)
    - source (original text metadata)
    """
    content = data.get("content", data)

    # Source metadata
    text_id = content.get("text_id", "")
    source_language = content.get("source_language", "en")
    target_language = content.get("target_language", "")
    domain = content.get("domain", "")
    original_text = content.get("text", "")

    # Translation from select_best_translation
    select_data = content.get("select_best_translation", {})
    if not isinstance(select_data, dict):
        select_data = {}

    best_translation = select_data.get(
        "best_translation",
        content.get("best_translation", ""),
    )
    selected_strategy = select_data.get(
        "selected_strategy",
        content.get("selected_strategy", ""),
    )
    selection_reasoning = select_data.get(
        "selection_reasoning",
        content.get("selection_reasoning", ""),
    )

    # Get confidence from scores
    scores = select_data.get("scores", content.get("scores", {}))
    confidence = 5
    if isinstance(scores, dict) and selected_strategy in scores:
        strategy_score = scores[selected_strategy]
        if isinstance(strategy_score, dict):
            confidence = strategy_score.get("confidence", 5)

    # Back-translation
    back_data = content.get("back_translate", {})
    if not isinstance(back_data, dict):
        back_data = {}
    back_translated_text = back_data.get(
        "back_translated_text",
        content.get("back_translated_text", ""),
    )

    # Quality validation
    validate_data = content.get("validate_quality", {})
    if not isinstance(validate_data, dict):
        validate_data = {}

    quality_score = validate_data.get(
        "quality_score",
        content.get("quality_score", 0),
    )
    meaning_preserved = validate_data.get(
        "meaning_preserved",
        content.get("meaning_preserved", False),
    )
    tone_preserved = validate_data.get(
        "tone_preserved",
        content.get("tone_preserved", False),
    )
    drift_issues = validate_data.get(
        "drift_issues",
        content.get("drift_issues", []),
    )
    quality_summary = validate_data.get(
        "quality_summary",
        content.get("quality_summary", ""),
    )

    # Count drift severities
    drift_count = len(drift_issues) if isinstance(drift_issues, list) else 0
    critical_issues = 0
    if isinstance(drift_issues, list):
        critical_issues = sum(
            1
            for issue in drift_issues
            if isinstance(issue, dict) and issue.get("severity") == "critical"
        )

    return {
        "text_id": text_id,
        "source_language": source_language,
        "target_language": target_language,
        "domain": domain,
        "translation": {
            "text": best_translation,
            "strategy": selected_strategy,
            "confidence": confidence,
        },
        "quality": {
            "score": quality_score,
            "meaning_preserved": meaning_preserved,
            "tone_preserved": tone_preserved,
            "drift_count": drift_count,
            "critical_issues": critical_issues,
        },
        "back_translation": back_translated_text,
        "original_text": original_text,
        "summary": quality_summary,
    }
