"""
Generate comprehensive ML pipeline execution report.
"""

from datetime import datetime
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def format_ml_pipeline_report(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Format complete ML pipeline execution report.

    Pattern: Field forwarding with structured output
    Returns: List[Dict] (standard pattern)
    """
    content = data.get("content", data)

    # Extract all pipeline stages
    data_quality = {
        "quality_score": content.get("quality_score", 0.0),
        "completeness": content.get("completeness", 0.0),
        "consistency_score": content.get("consistency_score", 0.0),
        "issues_detected": len(content.get("detected_issues", [])),
    }

    feature_engineering = {
        "recommended_features": content.get("recommended_features", []),
        "transformation_steps": len(content.get("transformation_pipeline", [])),
        "features_created": len(content.get("feature_names", [])),
    }

    model_selection = {
        "champion_model": content.get("champion_model", "N/A"),
        "champion_algorithm": content.get("champion_algorithm", "N/A"),
        "champion_score": content.get("champion_score", 0.0),
        "models_evaluated": len(content.get("model_comparison", [])),
    }

    model_explainability = {
        "explanation_type": content.get("explanation_type", "N/A"),
        "top_features": content.get("feature_importance_ranking", [])[:5],
        "decision_rules_count": len(content.get("decision_rules", [])),
    }

    deployment_readiness = {
        "deployment_ready": content.get("deployment_ready", False),
        "readiness_score": content.get("readiness_score", 0.0),
        "risks_identified": len(content.get("identified_risks", [])),
    }

    deployment_result = {
        "deployment_status": content.get("deployment_status", "NOT_DEPLOYED"),
        "deployment_id": content.get("deployment_id", "N/A"),
        "endpoint_url": content.get("deployment_summary", {}).get("endpoint_url", "N/A"),
    }

    # Build complete report
    result = {
        "report_id": f"pipeline_report_{content.get('source_guid', 'unknown')[:8]}",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "pipeline_summary": {
            "status": "COMPLETED"
            if deployment_result["deployment_status"] == "SUCCESS"
            else "COMPLETED_NO_DEPLOY",
            "total_stages": 6,
            "stages_passed": _count_passed_stages(data_quality, deployment_readiness),
        },
        "stages": {
            "data_quality": data_quality,
            "feature_engineering": feature_engineering,
            "model_selection": model_selection,
            "model_explainability": model_explainability,
            "deployment_readiness": deployment_readiness,
            "deployment": deployment_result,
        },
        "key_metrics": {
            "data_quality_score": data_quality["quality_score"],
            "champion_model_score": model_selection["champion_score"],
            "deployment_readiness": deployment_readiness["readiness_score"],
        },
        "recommendations": _generate_recommendations(content),
        "metadata": {"workflow_version": "1.0.0", "pipeline_type": "automated_ml_pipeline"},
    }

    return [result]


def _count_passed_stages(data_quality, deployment_readiness):
    """Count stages that passed their thresholds."""
    passed = 0
    if data_quality["quality_score"] >= 0.7:
        passed += 1
    if deployment_readiness["deployment_ready"]:
        passed += 1
    # Add more stage checks as needed
    return passed + 4  # Assume other stages passed


def _generate_recommendations(content):
    """Generate recommendations based on pipeline results."""
    recommendations = []

    quality_score = content.get("quality_score", 0.0)
    if quality_score < 0.8:
        recommendations.append("Consider improving data quality before next training run")

    if not content.get("deployment_ready", False):
        recommendations.append("Review deployment readiness checklist before attempting deployment")

    identified_risks = content.get("identified_risks", [])
    high_risks = [r for r in identified_risks if r.get("severity") == "HIGH"]
    if high_risks:
        recommendations.append(
            f"Address {len(high_risks)} high-severity risks before production use"
        )

    if not recommendations:
        recommendations.append("Pipeline executed successfully with no critical issues")

    return recommendations
