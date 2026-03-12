"""
Generate remediation plan enriched with historical fixes and topology constraints.
Demonstrates seed data enrichment pattern.
"""

from typing import Any

from agent_actions import udf_tool


def _find_similar_incidents(root_cause: str, historical_incidents: list[dict]) -> list[dict]:
    """Find incidents with similar root causes."""
    similar = []
    cause_keywords = set(root_cause.lower().split())

    for incident in historical_incidents:
        incident_cause = incident.get("root_cause", "").lower()
        incident_keywords = set(incident_cause.split())

        # Check for keyword overlap
        overlap = cause_keywords.intersection(incident_keywords)
        if len(overlap) >= 2 or any(kw in incident_cause for kw in cause_keywords if len(kw) > 5):
            similar.append(incident)

    return similar


def _extract_dependencies(root_service: str, system_topology: dict) -> list[str]:
    """Extract dependent services that may be affected."""
    services = system_topology.get("services", {})
    affected = []

    # Find the root service
    if root_service in services:
        # Direct dependencies
        deps = services[root_service].get("dependencies", [])
        affected.extend(deps)

    # Find services that depend on root_service
    for service_name, service_info in services.items():
        dependencies = service_info.get("dependencies", [])
        if root_service in dependencies:
            affected.append(service_name)

    return list(set(affected))


@udf_tool()
def generate_remediation_plan(data: dict[str, Any]) -> dict[str, Any]:
    """
    Generate remediation plan using historical incidents and system topology.

    Pattern: Seed data enrichment for intelligent recommendations
    Returns: Dict with remediation plan (passthrough handles upstream fields)
    """
    content = data.get("content", data)

    # Extract analysis results
    root_cause = content.get("root_cause", "Unknown")

    # Get seed data for enrichment
    historical_data = content.get("historical_incidents", {})
    historical_incidents = historical_data.get("incidents", [])
    common_patterns = historical_data.get("common_patterns", {})

    system_topology = content.get("system_topology", {})
    services = system_topology.get("services", {})

    # Find similar historical incidents
    similar_incidents = _find_similar_incidents(root_cause, historical_incidents)

    # Extract proven remediation steps from history
    immediate_actions = []
    mitigation_steps = []
    preventive_measures = []

    for incident in similar_incidents[:3]:  # Top 3 similar incidents
        resolution = incident.get("resolution", {})
        if resolution.get("immediate_action"):
            immediate_actions.append(
                {
                    "action": resolution["immediate_action"],
                    "source": f"Similar to {incident.get('id', 'unknown')}",
                    "effectiveness": "proven",
                }
            )
        if resolution.get("mitigation"):
            mitigation_steps.append(
                {
                    "action": resolution["mitigation"],
                    "source": f"Similar to {incident.get('id', 'unknown')}",
                }
            )
        if resolution.get("preventive_measure"):
            preventive_measures.append(
                {
                    "measure": resolution["preventive_measure"],
                    "source": f"Learned from {incident.get('id', 'unknown')}",
                }
            )

    # Identify affected service from root cause
    affected_service = None
    for service_name in services.keys():
        if service_name.replace("-", "_") in root_cause.lower().replace("-", "_"):
            affected_service = service_name
            break

    # Get dependencies that may need attention
    dependent_services = []
    monitoring_required = []
    if affected_service:
        dependent_services = _extract_dependencies(affected_service, system_topology)
        service_info = services.get(affected_service, {})
        monitoring_required = service_info.get("health_metrics", [])

    # Generate generic immediate actions if no historical match
    if not immediate_actions:
        immediate_actions.append(
            {
                "action": f"Isolate affected component: {affected_service or 'identified service'}",
                "source": "standard_practice",
                "effectiveness": "recommended",
            }
        )
        immediate_actions.append(
            {
                "action": "Enable circuit breaker to prevent cascade",
                "source": "standard_practice",
                "effectiveness": "recommended",
            }
        )

    # Match to common pattern for additional recommendations
    matched_pattern = None
    for pattern_name, pattern_info in common_patterns.items():
        if any(keyword in root_cause.lower() for keyword in pattern_name.split("_")):
            matched_pattern = {
                "pattern_name": pattern_name,
                "resolution_template": pattern_info.get("resolution_pattern", ""),
                "typical_causes": pattern_info.get("typical_causes", []),
            }
            break

    # Estimate recovery time based on historical data
    recovery_time_estimate = "Unknown"
    if similar_incidents:
        avg_resolution_time = sum(
            int(inc.get("time_to_resolve", "0").split()[0]) for inc in similar_incidents
        ) / len(similar_incidents)
        recovery_time_estimate = f"{int(avg_resolution_time)} minutes (based on historical data)"

    # Build monitoring checklist
    monitoring_checklist = []
    if monitoring_required:
        monitoring_checklist = [
            f"Monitor {metric} during remediation" for metric in monitoring_required
        ]

    # Add dependent service monitoring
    for dep_service in dependent_services[:5]:  # Limit to top 5
        if dep_service in services:
            dep_metrics = services[dep_service].get("health_metrics", [])
            if dep_metrics:
                monitoring_checklist.append(f"Watch {dep_service} - {dep_metrics[0]}")

    # Return ONLY new fields (passthrough forwards upstream fields)
    return {
        "immediate_actions": immediate_actions,
        "mitigation_steps": mitigation_steps,
        "preventive_measures": preventive_measures,
        "dependent_services_at_risk": dependent_services,
        "monitoring_checklist": monitoring_checklist,
        "matched_historical_pattern": matched_pattern,
        "similar_incident_count": len(similar_incidents),
        "recovery_time_estimate": recovery_time_estimate,
        "confidence": "high" if similar_incidents else "medium",
        "recommendations_source": "historical_data" if similar_incidents else "best_practices",
    }
