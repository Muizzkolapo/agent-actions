from typing import Any

from agent_actions import udf_tool


@udf_tool()
def package_triage_result(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble all upstream fields into a final triage record."""
    content = data.get("content", data)

    # Source fields (flattened from source.*)
    source = content.get("source", {})
    if isinstance(source, dict):
        ticket_id = source.get("id", content.get("id", "unknown"))
        title = source.get("title", content.get("title", ""))
        reporter = source.get("reporter", content.get("reporter", ""))
    else:
        ticket_id = content.get("id", "unknown")
        title = content.get("title", "")
        reporter = content.get("reporter", "")

    # output_field values arrive under the ACTION name, not the field name
    issue_type = content.get("classify_issue", content.get("issue_type", "unclassified"))
    severity = content.get("assess_severity", content.get("severity", "medium"))
    product_area = content.get("identify_area", content.get("product_area", "unknown"))
    assigned_team = content.get("assign_team", content.get("assigned_team", "support"))
    summary = content.get("summarize_issue", content.get("summary", ""))
    suggested_response = content.get("draft_response", content.get("suggested_response", ""))

    return [{
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
    }]
