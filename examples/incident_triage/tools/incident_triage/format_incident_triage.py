"""
Format complete incident triage output.
Demonstrates field forwarding and output formatting pattern.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def format_incident_triage(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Format complete triage output with all assessments.

    Pattern: Field forwarding with structured output
    Returns: List[Dict] (standard pattern)
    """
    content = data.get("content", data)

    # Extract all components
    incident_details = {
        "title": content.get("title", "Unknown Incident"),
        "description": content.get("description", ""),
        "affected_systems": content.get("affected_systems", []),
        "reporter_priority": content.get("reporter_priority", "UNKNOWN"),
    }

    severity_assessment = {
        "final_severity": content.get("final_severity", "SEV5"),
        "confidence_score": content.get("confidence_score", 0.0),
        "is_split_decision": content.get("is_split_decision", False),
        "vote_summary": content.get("vote_summary", ""),
    }

    impact_assessment = {
        "customer_impact": {
            "level": content.get("customer_impact_level", "UNKNOWN"),
            "affected_count": content.get("affected_customer_count_estimate", ""),
            "revenue_impact": content.get("revenue_impact_estimate", ""),
            "customer_facing": content.get("customer_facing", False),
        },
        "system_impact": {
            "level": content.get("system_impact_level", "UNKNOWN"),
            "affected_services": content.get("affected_services", []),
            "degradation": content.get("degradation_percentage", ""),
            "cascading_risk": content.get("cascading_failure_risk", ""),
        },
    }

    team_assignment = {
        "assigned_teams": content.get("assigned_teams", []),
        "primary_system": content.get("primary_system", "unknown"),
        "urgency_level": content.get("urgency_level", ""),
        "escalation_path": content.get("escalation_path", []),
    }

    response_plan = {
        "immediate_actions": content.get("immediate_actions", []),
        "investigation_steps": content.get("investigation_steps", []),
        "communication_plan": content.get("communication_plan", ""),
        "escalation_criteria": content.get("escalation_criteria", []),
        "estimated_tte": content.get("estimated_tte", "TBD"),
    }

    # Executive summary (if present)
    executive_summary = None
    if content.get("executive_summary"):
        executive_summary = {
            "summary": content.get("executive_summary", ""),
            "business_impact": content.get("business_impact_summary", ""),
            "response_status": content.get("response_status", ""),
            "stakeholders": content.get("key_stakeholders", []),
        }

    # Build complete triage output
    result = {
        "triage_id": content.get("source_guid", "unknown"),
        "timestamp": content.get("timestamp", ""),
        "incident": incident_details,
        "severity": severity_assessment,
        "impact": impact_assessment,
        "teams": team_assignment,
        "response": response_plan,
        "executive_summary": executive_summary,
        "metadata": {
            "workflow_version": "1.0.0",
            "requires_executive_notification": content.get(
                "requires_executive_notification", False
            ),
            "triage_completed": True,
        },
    }

    # Return as list (required by framework)
    return [result]
