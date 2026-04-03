"""
Dynamic team assignment based on affected systems and severity.
Demonstrates content injection pattern with passthrough.
"""

from typing import Any

from agent_actions import udf_tool

# Team routing rules based on affected systems
TEAM_ROUTING = {
    "api": {
        "primary": "backend-oncall",
        "secondary": "platform-oncall",
        "escalation": "engineering-leads",
    },
    "database": {
        "primary": "data-oncall",
        "secondary": "backend-oncall",
        "escalation": "data-leads",
    },
    "frontend": {
        "primary": "frontend-oncall",
        "secondary": "platform-oncall",
        "escalation": "product-engineering",
    },
    "payment": {
        "primary": "payments-oncall",
        "secondary": "backend-oncall",
        "escalation": "security-team",
    },
    "auth": {
        "primary": "security-oncall",
        "secondary": "backend-oncall",
        "escalation": "security-leads",
    },
}

SEVERITY_ESCALATION = {
    "SEV1": ["primary", "secondary", "escalation"],
    "SEV2": ["primary", "secondary"],
    "SEV3": ["primary"],
    "SEV4": ["primary"],
    "SEV5": ["primary"],
}


@udf_tool()
def assign_team_based_on_impact(data: dict[str, Any]) -> dict[str, Any]:
    """
    Assign response teams dynamically based on affected systems and severity.

    Pattern: Content injection with passthrough + seed data enrichment
    Returns: Dict with ONLY new fields (passthrough handles the rest)
    """
    content = data.get("content", data)

    # Extract context
    severity = content.get("final_severity", "SEV3")
    affected_services = content.get("affected_services", [])

    # Get seed data for enrichment
    team_roster = content.get("team_roster", {}).get("oncall_teams", {})
    service_catalog = content.get("service_catalog", {}).get("services", {})

    # Initialize variables with defaults to avoid unbound errors
    primary_team = None
    matched_service = None
    service_tier = "unknown"
    primary_system = None
    response_sla = "Unknown"

    # Try to match affected services to service catalog
    for service in affected_services:
        service_lower = str(service).lower()
        for service_key, service_info in service_catalog.items():
            if (
                service_key in service_lower
                or service_info.get("name", "").lower() in service_lower
            ):
                primary_team = service_info.get("owner_team")
                matched_service = service_info.get("name")
                service_tier = service_info.get("tier")
                break
        if primary_team:
            break

    # Fallback to rule-based routing if no catalog match
    if not primary_team:
        for service in affected_services:
            service_lower = str(service).lower()
            for key in TEAM_ROUTING.keys():
                if key in service_lower:
                    primary_system = key
                    break
            if primary_system:
                break

        # Default to backend if unknown
        if not primary_system:
            primary_system = "api"

        routing = TEAM_ROUTING[primary_system]
        escalation_levels = SEVERITY_ESCALATION.get(severity, ["primary"])

        # Build team list from hardcoded routing
        assigned_teams = []
        for level in escalation_levels:
            team = routing.get(level)
            if team and team not in assigned_teams:
                assigned_teams.append(team)
    else:
        # Use catalog-based team assignment
        assigned_teams = [primary_team]

        # Add escalation based on severity
        escalation_levels = SEVERITY_ESCALATION.get(severity, ["primary"])
        if len(escalation_levels) > 1 and team_roster.get(primary_team):
            # Add escalation team if needed
            if "secondary" in escalation_levels:
                assigned_teams.append("platform-oncall")

    # Enrich with team metadata from roster
    team_contacts = []
    team_slacks = []
    for team in assigned_teams:
        if team in team_roster:
            team_info = team_roster[team]
            team_contacts.append(team_info.get("primary_contact", team))
            team_slacks.append(team_info.get("slack_channel", "#incidents"))

    # Get SLA from team roster (override default if available)
    if primary_team and primary_team in team_roster:
        sla_info = team_roster[primary_team].get("sla", {})
        response_sla = sla_info.get(severity, response_sla)

    # Generate dynamic response message
    system_name = matched_service or (primary_system.upper() if primary_system else "UNKNOWN")
    response_message = f"🚨 {severity} incident affecting {system_name}"

    # Add urgency indicator
    urgency_indicators = {
        "SEV1": "🔴 CRITICAL - Page immediately",
        "SEV2": "🟠 HIGH - Notify now",
        "SEV3": "🟡 MEDIUM - Standard response",
        "SEV4": "🟢 LOW - Queue for review",
        "SEV5": "ℹ️ INFO - For awareness",
    }
    urgency = urgency_indicators.get(severity, "Standard response")

    # Return ONLY new fields (passthrough forwards upstream fields)
    return {
        "assigned_teams": assigned_teams,
        "team_contacts": team_contacts,
        "team_slack_channels": team_slacks,
        "primary_system": matched_service or primary_system or "unknown",
        "service_tier": service_tier,
        "response_sla": response_sla,
        "response_message": response_message,
        "urgency_level": urgency,
        "requires_executive_notification": severity in ["SEV1", "SEV2"],
        "escalation_path": escalation_levels,
        "team_routing_source": "service_catalog" if matched_service else "fallback_rules",
    }
