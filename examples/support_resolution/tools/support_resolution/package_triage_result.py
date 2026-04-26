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

    # output_field values arrive under the ACTION name, not the field name
    issue_type = data.get("classify_issue", data.get("issue_type", "unclassified"))
    severity = data.get("assess_severity", data.get("severity", "medium"))
    product_area = data.get("identify_area", data.get("product_area", "unknown"))
    assigned_team = data.get("assign_team", data.get("assigned_team", "support"))
    summary = data.get("summarize_issue", data.get("summary", ""))
    suggested_response = data.get("draft_response", data.get("suggested_response", ""))

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
