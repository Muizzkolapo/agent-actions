"""
Format comprehensive root cause analysis report.
Aggregates all analysis results into structured output.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def format_rca_report(data: dict[str, Any]) -> dict[str, Any]:
    """
    Format complete root cause analysis report with all findings.

    Pattern: Output aggregation and formatting
    Returns: Comprehensive RCA report
    """
    content = data.get("content", data)

    # Extract all analysis stages
    anomaly_signals = {
        "anomaly_type": content.get("anomaly_type", "Unknown"),
        "affected_components": content.get("affected_components", []),
        "observed_symptoms": content.get("observed_symptoms", []),
        "severity": content.get("severity", "Unknown"),
        "timestamp_range": content.get("timestamp_range", "Unknown"),
    }

    causal_analysis = {
        "root_cause": content.get("root_cause", "Unknown"),
        "intermediate_causes": content.get("intermediate_causes", []),
        "causal_mechanism": content.get("causal_mechanism", "Unknown"),
        "propagation_path": content.get("propagation_path", []),
        "contributing_factors": content.get("contributing_factors", []),
    }

    impact_assessment = {
        "impact_magnitude": content.get("impact_magnitude", "Unknown"),
        "affected_metrics": content.get("affected_metrics", []),
        "estimated_effect_size": content.get("estimated_effect_size", "Unknown"),
        "blast_radius": content.get("blast_radius", []),
        "business_impact": content.get("business_impact", "Unknown"),
    }

    remediation_plan = {
        "immediate_actions": content.get("immediate_actions", []),
        "mitigation_steps": content.get("mitigation_steps", []),
        "preventive_measures": content.get("preventive_measures", []),
        "dependent_services_at_risk": content.get("dependent_services_at_risk", []),
        "monitoring_checklist": content.get("monitoring_checklist", []),
        "recovery_time_estimate": content.get("recovery_time_estimate", "Unknown"),
        "confidence": content.get("confidence", "medium"),
    }

    hypothesis_analysis = {
        "hypothesis_count": content.get("hypothesis_count", 0),
        "top_hypotheses": content.get("top_hypotheses", []),
        "strategy_distribution": content.get("strategy_distribution", {}),
        "ranking_method": content.get("ranking_method", "unknown"),
    }

    validation_results = {
        "validated_hypotheses": content.get("validated_hypotheses", []),
        "evidence_analysis": content.get("evidence_analysis", "No analysis available"),
        "confidence_scores": content.get("confidence_scores", {}),
        "contradicting_evidence": content.get("contradicting_evidence", []),
    }

    # Generate executive summary
    root_cause = causal_analysis["root_cause"]
    severity = anomaly_signals["severity"]
    affected_count = len(anomaly_signals["affected_components"])

    executive_summary = (
        f"{severity} incident affecting {affected_count} component(s). "
        f"Root cause identified: {root_cause}. "
    )

    if remediation_plan["recovery_time_estimate"] != "Unknown":
        executive_summary += (
            f"Estimated recovery time: {remediation_plan['recovery_time_estimate']}. "
        )

    if remediation_plan["confidence"] == "high":
        executive_summary += "High confidence in remediation plan based on historical data."
    else:
        executive_summary += "Remediation plan based on best practices."

    # Generate timeline of causal chain
    timeline = []
    propagation_path = causal_analysis.get("propagation_path", [])
    for idx, step in enumerate(propagation_path):
        timeline.append(
            {
                "sequence": idx + 1,
                "event": step,
                "type": "root_cause"
                if idx == 0
                else ("effect" if idx == len(propagation_path) - 1 else "intermediate"),
            }
        )

    # Compile complete report
    return {
        "report_type": "Root Cause Analysis",
        "generated_at": "timestamp",  # Would be populated by workflow engine
        "executive_summary": executive_summary,
        "anomaly_detection": anomaly_signals,
        "causal_analysis": causal_analysis,
        "impact_assessment": impact_assessment,
        "remediation_plan": remediation_plan,
        "analysis_details": {
            "hypothesis_analysis": hypothesis_analysis,
            "validation_results": validation_results,
            "causal_timeline": timeline,
        },
        "confidence_level": remediation_plan["confidence"],
        "data_sources": {
            "used_historical_data": content.get("similar_incident_count", 0) > 0,
            "used_topology_data": len(content.get("dependent_services_at_risk", [])) > 0,
            "used_causal_patterns": content.get("used_seed_patterns", False),
        },
    }
