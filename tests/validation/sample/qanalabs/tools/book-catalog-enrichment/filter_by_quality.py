"""Filter catalog entries by quality score."""

from typing import Any, Dict, List, TypedDict

from agent_actions import udf_tool


class FilterQualityInput(TypedDict, total=False):
    """Input schema for filter_by_quality.

    Source: node_8_format_entry output (CatalogEntryOutput)
    Destination: node_9_filter_quality output
    """

    # Identifiers
    isbn: str
    catalog_id: str

    # Core metadata
    title: str
    authors: List[str]
    publisher: str
    publish_year: int
    page_count: int

    # Classification
    primary_category: str
    categories: List[str]
    bisac_codes: List[str]

    # Marketing content
    short_description: str
    full_description: str
    key_selling_points: List[str]
    target_audience: str

    # SEO
    seo_keywords: List[str]
    meta_title: str
    meta_description: str

    # Recommendations
    similar_titles: List[Dict[str, Any]]
    reading_path: str

    # Reading info
    difficulty_level: str
    experience_required: str
    prerequisites: List[str]
    reading_time_hours: str

    # Quality
    quality_score: float
    publication_ready: bool

    # Metadata
    enrichment_version: str
    enriched_fields: List[str]


MINIMUM_QUALITY_SCORE = 3.0
MINIMUM_ENRICHED_FIELDS = 3


class FilterQualityOutput(TypedDict, total=False):
    """Output schema for filter_by_quality."""

    passes_filter: bool
    filter_reason: str


@udf_tool(input_type=FilterQualityInput, output_type=FilterQualityOutput)
def filter_by_quality(data: dict) -> dict:
    """Filter catalog entries that don't meet quality thresholds.

    Args:
        data: Catalog entry with quality scores

    Returns:
        Filter result (only output fields)
    """
    quality_score = data.get("quality_score", 0)
    publication_ready = data.get("publication_ready", False)
    enriched_fields = data.get("enriched_fields", [])

    reasons = []

    # Check quality score
    if quality_score < MINIMUM_QUALITY_SCORE:
        reasons.append(f"Quality score {quality_score} below minimum {MINIMUM_QUALITY_SCORE}")

    # Check enriched fields count
    if len(enriched_fields) < MINIMUM_ENRICHED_FIELDS:
        reasons.append(
            f"Only {len(enriched_fields)} fields enriched, need {MINIMUM_ENRICHED_FIELDS}"
        )

    # Check publication readiness
    if not publication_ready:
        reasons.append("Not marked as publication ready")

    passes = len(reasons) == 0

    # Return only the output fields defined in FilterQualityOutput
    return {
        "passes_filter": passes,
        "filter_reason": "; ".join(reasons) if reasons else "Passed all quality checks",
    }
