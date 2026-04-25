from typing import Any

from agent_actions import udf_tool


def _unwrap(namespace: Any, field: str, default: str = "") -> str:
    """Extract a field from a namespace dict, or return the value if already a string."""
    if isinstance(namespace, dict):
        return namespace.get(field, default)
    if isinstance(namespace, str):
        return namespace
    return default


@udf_tool()
def package_triage_result(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble all upstream fields into a final triage record."""
    content = data.get("content", data)

    # Source fields — namespace dict: {"id": ..., "title": ..., "reporter": ...}
    source = content.get("source", {})
    ticket_id = source.get("id", "unknown") if isinstance(source, dict) else "unknown"
    title = source.get("title", "") if isinstance(source, dict) else ""
    reporter = source.get("reporter", "") if isinstance(source, dict) else ""

    # output_field values: each namespace is {"field_name": "value"}
    issue_type = _unwrap(content.get("classify_issue", {}), "issue_type", "unclassified")
    severity = _unwrap(content.get("assess_severity", {}), "severity", "medium")
    product_area = _unwrap(content.get("identify_area", {}), "product_area", "unknown")
    assigned_team = _unwrap(content.get("assign_team", {}), "assigned_team", "support")
    summary = _unwrap(content.get("summarize_issue", {}), "summary", "")
    suggested_response = _unwrap(content.get("draft_response", {}), "suggested_response", "")

    return [
        {
            "ticket_id": ticket_id,
            "title": title,
            "reporter": reporter,
            "issue_type": issue_type,
            "severity": severity,
            "product_area": product_area,
            "assigned_team": assigned_team,
            "summary": summary,
            "suggested_response": suggested_response,
            "status": "triaged",
        }
    ]
