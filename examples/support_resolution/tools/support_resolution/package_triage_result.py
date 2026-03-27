from typing import Any

from agent_actions import udf_tool


@udf_tool()
def package_triage_result(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble all upstream fields into a final triage record."""
    content = data.get("content", data)

    return [{
        "ticket_id": content.get("id", "unknown"),
        "title": content.get("title", ""),
        "reporter": content.get("reporter", ""),
        "issue_type": content.get("issue_type", "unclassified"),
        "severity": content.get("severity", "medium"),
        "product_area": content.get("product_area", "unknown"),
        "assigned_team": content.get("assigned_team", "support"),
        "summary": content.get("summary", ""),
        "suggested_response": content.get("suggested_response", ""),
        "status": "triaged",
    }]
