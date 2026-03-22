"""Build user-specific views of the enriched catalog entry."""

from agent_actions import udf_tool


@udf_tool()
def select_for_users(data: dict) -> dict:
    """Build SEO, management, and developer views from the enriched catalog entry."""
    content = data.get("content", data)

    seo_view = {
        "isbn": content.get("isbn", ""),
        "title": content.get("title", ""),
        "meta_title": content.get("meta_title", ""),
        "meta_description": content.get("meta_description", ""),
        "seo_keywords": content.get("seo_keywords", []),
        "target_audience": content.get("target_audience", ""),
        "marketing_description": content.get("full_description", ""),
        "hook_sentence": content.get("short_description", ""),
        "key_selling_points": content.get("key_selling_points", []),
    }

    management_view = {
        "isbn": content.get("isbn", ""),
        "title": content.get("title", ""),
        "catalog_id": content.get("catalog_id", ""),
        "quality_score": content.get("quality_score", 0),
        "publication_ready": content.get("publication_ready", False),
        "primary_category": content.get("primary_category", ""),
        "target_audience": content.get("target_audience", ""),
        "enriched_fields": content.get("enriched_fields", []),
        "enrichment_version": content.get("enrichment_version", ""),
        "filter_reason": content.get("filter_reason", ""),
    }

    developer_view = {
        "isbn": content.get("isbn", ""),
        "title": content.get("title", ""),
        "bisac_codes": content.get("bisac_codes", []),
        "primary_category": content.get("primary_category", ""),
        "difficulty_level": content.get("difficulty_level", ""),
        "experience_required": content.get("experience_required", ""),
        "prerequisites": content.get("prerequisites", []),
        "reading_time_hours": content.get("reading_time_hours", ""),
        "similar_titles": content.get("similar_titles", []),
        "reading_path": content.get("reading_path", ""),
    }

    return {
        "isbn": content.get("isbn", ""),
        "title": content.get("title", ""),
        "seo_view": seo_view,
        "management_view": management_view,
        "developer_view": developer_view,
    }
