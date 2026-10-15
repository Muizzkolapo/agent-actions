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
    # A record tool reads each observed action under its name. An action whose guard
    # skipped the record is there as None.
    details = data.get("extract_incident_details") or {}
    severity = data.get("aggregate_severity") or {}
    customer = data.get("assess_customer_impact") or {}
    system = data.get("assess_system_impact") or {}
    team = data.get("assign_response_team") or {}
    plan = data.get("generate_response_plan") or {}
    summary = data.get("generate_executive_summary") or {}
    timestamp = (data.get("source") or {}).get("timestamp", "")

    # Extract all components
    incident_details = {
        "title": details.get("title", "Unknown Incident"),
        "description": details.get("description", ""),
        "affected_systems": details.get("affected_systems", []),
        "reporter_priority": details.get("reporter_priority", "UNKNOWN"),
    }

    severity_assessment = {
        "final_severity": severity.get("final_severity", "SEV5"),
        "confidence_score": severity.get("confidence_score", 0.0),
        "is_split_decision": severity.get("is_split_decision", False),
        "vote_summary": severity.get("vote_summary", ""),
    }

    impact_assessment = {
        "customer_impact": {
            "level": customer.get("customer_impact_level", "UNKNOWN"),
            "affected_count": customer.get("affected_customer_count_estimate", ""),
            "revenue_impact": customer.get("revenue_impact_estimate", ""),
            "customer_facing": customer.get("customer_facing", False),
        },
        "system_impact": {
            "level": system.get("system_impact_level", "UNKNOWN"),
            "affected_services": system.get("affected_services", []),
            "degradation": system.get("degradation_percentage", ""),
            "cascading_risk": system.get("cascading_failure_risk", ""),
        },
    }

    team_assignment = {
        "assigned_teams": team.get("assigned_teams", []),
        "primary_system": team.get("primary_system", "unknown"),
        "urgency_level": team.get("urgency_level", ""),
        "escalation_path": team.get("escalation_path", []),
    }

    response_plan = {
        "immediate_actions": plan.get("immediate_actions", []),
        "investigation_steps": plan.get("investigation_steps", []),
        "communication_plan": plan.get("communication_plan", ""),
        "escalation_criteria": plan.get("escalation_criteria", []),
        "estimated_tte": plan.get("estimated_tte", "TBD"),
    }

    # Executive summary (if present, empty object if not — schema requires object type)
    executive_summary = {}
    if summary.get("executive_summary"):
        executive_summary = {
            "summary": summary.get("executive_summary", ""),
            "business_impact": summary.get("business_impact_summary", ""),
            "response_status": summary.get("response_status", ""),
            "stakeholders": summary.get("key_stakeholders", []),
        }

    # Build complete triage output
    result = {
        "triage_id": f"triage-{timestamp}" if timestamp else "unknown",
        "timestamp": timestamp,
        "incident": incident_details,
        "severity": severity_assessment,
        "impact": impact_assessment,
        "teams": team_assignment,
        "response": response_plan,
        "executive_summary": executive_summary,
        "metadata": {
            "workflow_version": "1.0.0",
            "requires_executive_notification": team.get("requires_executive_notification", False),
            "triage_completed": True,
        },
    }

    # Return as list (required by framework)
    return [result]
