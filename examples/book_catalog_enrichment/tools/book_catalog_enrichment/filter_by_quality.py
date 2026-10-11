"""Filter catalog entries by quality score."""

from agent_actions import udf_tool

MINIMUM_QUALITY_SCORE = 3.0
MINIMUM_ENRICHED_FIELDS = 3


@udf_tool()
def filter_by_quality(data: dict) -> dict:
    """Filter catalog entries that don't meet quality thresholds."""
    # A record tool is handed one key per observed action.
    format_entry = data.get("format_entry", {})
    quality_score = format_entry.get("quality_score", 0)
    publication_ready = format_entry.get("publication_ready", False)
    enriched_fields = format_entry.get("enriched_fields", [])

    reasons = []

    if quality_score < MINIMUM_QUALITY_SCORE:
        reasons.append(f"Quality score {quality_score} below minimum {MINIMUM_QUALITY_SCORE}")

    if len(enriched_fields) < MINIMUM_ENRICHED_FIELDS:
        reasons.append(
            f"Only {len(enriched_fields)} fields enriched, need {MINIMUM_ENRICHED_FIELDS}"
        )

    if not publication_ready:
        reasons.append("Not marked as publication ready")

    passes = len(reasons) == 0

    return {
        "passes_filter": passes,
        "filter_reason": "; ".join(reasons) if reasons else "Passed all quality checks",
    }
