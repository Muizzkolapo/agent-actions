from typing import Any

from agent_actions import udf_tool


@udf_tool()
def package_triage_result(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble all upstream fields into a final triage record."""
    # Source fields (flattened from source.*)
    source = data.get("source", {})
    if isinstance(source, dict):
        ticket_id = source.get("id", data.get("id", "unknown"))
        title = source.get("title", data.get("title", ""))
        reporter = source.get("reporter", data.get("reporter", ""))
    else:
        ticket_id = data.get("id", "unknown")
        title = data.get("title", "")
        reporter = data.get("reporter", "")

    # output_field values arrive namespaced under the ACTION name.
    # The value may be a raw string OR a dict like {"field_name": "value"} —
    # handle both for resilience.
    def _extract(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, dict):
            return str(next(iter(val.values()), "")) if val else ""
        return str(val)

    issue_type = _extract(data.get("classify_issue", data.get("issue_type", "unclassified")))
    severity = _extract(data.get("assess_severity", data.get("severity", "medium")))
    product_area = _extract(data.get("identify_area", data.get("product_area", "unknown")))
    assigned_team = _extract(data.get("assign_team", data.get("assigned_team", "support")))
    summary = _extract(data.get("summarize_issue", data.get("summary", "")))
    suggested_response = _extract(data.get("draft_response", data.get("suggested_response", "")))

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
