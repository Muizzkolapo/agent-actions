"""Format the final enriched catalog entry."""

from typing import Any, Dict, List, TypedDict

from agent_actions import udf_tool


class FormatCatalogInput(TypedDict, total=False):
    """Input schema for format_catalog_entry.

    Source: node_7_score_quality output
    Destination: node_8_format_entry output
    """

    # Original book metadata
    isbn: str
    title: str
    authors: List[str]
    publisher: str
    publish_year: int
    page_count: int
    raw_description: str

    # Enriched data - Classification
    bisac_codes: List[str]
    bisac_names: List[str]

    # Enriched data - Marketing
    marketing_description: str
    hook_sentence: str
    key_benefits: List[str]
    target_audience: str

    # Enriched data - SEO
    primary_keywords: List[str]
    long_tail_keywords: List[str]
    meta_title: str
    meta_description: str

    # Enriched data - Recommendations
    similar_books: List[Dict[str, str]]
    reading_path: str

    # Enriched data - Reading Level
    reading_level: str
    years_experience_needed: str
    prerequisites: List[str]
    estimated_reading_time: str

    # Quality scores
    overall_score: int
    dimension_scores: Dict[str, int]
    improvement_suggestions: List[str]
    ready_for_publication: bool


class CatalogEntryOutput(TypedDict, total=False):
    """Output schema - the final catalog entry."""

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


@udf_tool(input_type=FormatCatalogInput, output_type=CatalogEntryOutput)
def format_catalog_entry(data: dict) -> dict:
    """Format all enriched data into a clean catalog entry.

    Args:
        data: All enriched book data

    Returns:
        Formatted catalog entry ready for publication
    """
    # Track which fields were enriched
    enriched_fields = []

    # Build the catalog entry
    entry = {
        # Identifiers
        "isbn": data.get("isbn", ""),
        "catalog_id": f"CAT-{data.get('isbn', 'UNKNOWN')[-6:]}",
        # Core metadata (passed through)
        "title": data.get("title", ""),
        "authors": data.get("authors", []),
        "publisher": data.get("publisher", ""),
        "publish_year": data.get("publish_year", 0),
        "page_count": data.get("page_count", 0),
    }

    # Classification
    bisac_names = data.get("bisac_names", [])
    entry["primary_category"] = bisac_names[0] if bisac_names else "Uncategorized"
    entry["categories"] = bisac_names
    entry["bisac_codes"] = data.get("bisac_codes", [])
    if bisac_names:
        enriched_fields.append("classification")

    # Marketing content
    hook = data.get("hook_sentence", "")
    full_desc = data.get("marketing_description", "")
    entry["short_description"] = (
        hook if hook else full_desc[:200] + "..." if len(full_desc) > 200 else full_desc
    )
    entry["full_description"] = full_desc
    entry["key_selling_points"] = data.get("key_benefits", [])
    entry["target_audience"] = data.get("target_audience", "")
    if full_desc:
        enriched_fields.append("marketing_description")

    # SEO
    primary_kw = data.get("primary_keywords", [])
    long_tail_kw = data.get("long_tail_keywords", [])
    entry["seo_keywords"] = primary_kw + long_tail_kw
    entry["meta_title"] = data.get("meta_title", data.get("title", ""))
    entry["meta_description"] = data.get("meta_description", "")
    if primary_kw:
        enriched_fields.append("seo_keywords")

    # Recommendations
    similar = data.get("similar_books", [])
    entry["similar_titles"] = similar[:5] if similar else []  # Max 5
    entry["reading_path"] = data.get("reading_path", "")
    if similar:
        enriched_fields.append("recommendations")

    # Reading info
    entry["difficulty_level"] = data.get("reading_level", "Intermediate")
    entry["experience_required"] = data.get("years_experience_needed", "")
    entry["prerequisites"] = data.get("prerequisites", [])
    entry["reading_time_hours"] = data.get("estimated_reading_time", "")
    if data.get("reading_level"):
        enriched_fields.append("reading_level")

    # Quality
    entry["quality_score"] = float(data.get("overall_score", 0))
    entry["publication_ready"] = data.get("ready_for_publication", False)

    # Metadata
    entry["enrichment_version"] = "1.0.0"
    entry["enriched_fields"] = enriched_fields

    return entry
