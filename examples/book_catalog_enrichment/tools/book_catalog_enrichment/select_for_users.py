"""Build user-specific views of the enriched catalog entry."""

from agent_actions import udf_tool


@udf_tool()
def select_for_users(data: dict) -> dict:
    """Build SEO, management, and developer views from the enriched catalog entry."""
    seo_view = {
        "isbn": data.get("isbn", ""),
        "title": data.get("title", ""),
        "meta_title": data.get("meta_title", ""),
        "meta_description": data.get("meta_description", ""),
        "seo_keywords": data.get("seo_keywords", []),
        "target_audience": data.get("target_audience", ""),
        "marketing_description": data.get("full_description", ""),
        "hook_sentence": data.get("short_description", ""),
        "key_selling_points": data.get("key_selling_points", []),
    }

    management_view = {
        "isbn": data.get("isbn", ""),
        "title": data.get("title", ""),
        "catalog_id": data.get("catalog_id", ""),
        "quality_score": data.get("quality_score", 0),
        "publication_ready": data.get("publication_ready", False),
        "primary_category": data.get("primary_category", ""),
        "target_audience": data.get("target_audience", ""),
        "enriched_fields": data.get("enriched_fields", []),
        "enrichment_version": data.get("enrichment_version", ""),
        "filter_reason": data.get("filter_reason", ""),
    }

    developer_view = {
        "isbn": data.get("isbn", ""),
        "title": data.get("title", ""),
        "bisac_codes": data.get("bisac_codes", []),
        "primary_category": data.get("primary_category", ""),
        "difficulty_level": data.get("difficulty_level", ""),
        "experience_required": data.get("experience_required", ""),
        "prerequisites": data.get("prerequisites", []),
        "reading_time_hours": data.get("reading_time_hours", ""),
        "similar_titles": data.get("similar_titles", []),
        "reading_path": data.get("reading_path", ""),
    }

    return {
        "isbn": data.get("isbn", ""),
        "title": data.get("title", ""),
        "seo_view": seo_view,
        "management_view": management_view,
        "developer_view": developer_view,
    }
