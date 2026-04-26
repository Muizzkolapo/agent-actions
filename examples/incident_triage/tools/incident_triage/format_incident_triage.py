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
    # Extract all components
    incident_details = {
        "title": data.get("title", "Unknown Incident"),
        "description": data.get("description", ""),
        "affected_systems": data.get("affected_systems", []),
        "reporter_priority": data.get("reporter_priority", "UNKNOWN"),
    }

    severity_assessment = {
        "final_severity": data.get("final_severity", "SEV5"),
        "confidence_score": data.get("confidence_score", 0.0),
        "is_split_decision": data.get("is_split_decision", False),
        "vote_summary": data.get("vote_summary", ""),
    }

    impact_assessment = {
        "customer_impact": {
            "level": data.get("customer_impact_level", "UNKNOWN"),
            "affected_count": data.get("affected_customer_count_estimate", ""),
            "revenue_impact": data.get("revenue_impact_estimate", ""),
            "customer_facing": data.get("customer_facing", False),
        },
        "system_impact": {
            "level": data.get("system_impact_level", "UNKNOWN"),
            "affected_services": data.get("affected_services", []),
            "degradation": data.get("degradation_percentage", ""),
            "cascading_risk": data.get("cascading_failure_risk", ""),
        },
    }

    team_assignment = {
        "assigned_teams": data.get("assigned_teams", []),
        "primary_system": data.get("primary_system", "unknown"),
        "urgency_level": data.get("urgency_level", ""),
        "escalation_path": data.get("escalation_path", []),
    }

    response_plan = {
        "immediate_actions": data.get("immediate_actions", []),
        "investigation_steps": data.get("investigation_steps", []),
        "communication_plan": data.get("communication_plan", ""),
        "escalation_criteria": data.get("escalation_criteria", []),
        "estimated_tte": data.get("estimated_tte", "TBD"),
    }

    # Executive summary (if present, empty object if not — schema requires object type)
    executive_summary = {}
    if data.get("executive_summary"):
        executive_summary = {
            "summary": data.get("executive_summary", ""),
            "business_impact": data.get("business_impact_summary", ""),
            "response_status": data.get("response_status", ""),
            "stakeholders": data.get("key_stakeholders", []),
        }

    # Build complete triage output
    result = {
        "triage_id": data.get("source_guid", "unknown"),
        "timestamp": data.get("timestamp", ""),
        "incident": incident_details,
        "severity": severity_assessment,
        "impact": impact_assessment,
        "teams": team_assignment,
        "response": response_plan,
        "executive_summary": executive_summary,
        "metadata": {
            "workflow_version": "1.0.0",
            "requires_executive_notification": data.get("requires_executive_notification", False),
            "triage_completed": True,
        },
    }

    # Return as list (required by framework)
    return [result]
