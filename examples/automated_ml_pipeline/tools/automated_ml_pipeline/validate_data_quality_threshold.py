"""
Validate that data quality meets the threshold for ML training.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def validate_data_quality_threshold(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Validate data quality threshold for ML pipeline.

    Pattern: Quality gate validation
    Returns: List[Dict] with validation result
    """
    content = data.get("content", data)

    quality_score = content.get("quality_score", 0.0)
    completeness = content.get("completeness", 0.0)
    consistency_score = content.get("consistency_score", 0.0)
    detected_issues = content.get("detected_issues", [])

    # Define thresholds
    QUALITY_THRESHOLD = 0.7
    COMPLETENESS_THRESHOLD = 0.8
    CONSISTENCY_THRESHOLD = 0.7

    # Evaluate thresholds
    quality_pass = quality_score >= QUALITY_THRESHOLD
    completeness_pass = completeness >= COMPLETENESS_THRESHOLD
    consistency_pass = consistency_score >= CONSISTENCY_THRESHOLD

    # Check for critical issues
    critical_issues = [i for i in detected_issues if i.get("severity") == "HIGH"]
    no_critical_issues = len(critical_issues) == 0

    # Overall validation
    validation_passed = all([quality_pass, completeness_pass, consistency_pass, no_critical_issues])

    result = {
        "validation_passed": validation_passed,
        "quality_score": quality_score,
        "threshold_results": {
            "quality": {
                "value": quality_score,
                "threshold": QUALITY_THRESHOLD,
                "passed": quality_pass,
            },
            "completeness": {
                "value": completeness,
                "threshold": COMPLETENESS_THRESHOLD,
                "passed": completeness_pass,
            },
            "consistency": {
                "value": consistency_score,
                "threshold": CONSISTENCY_THRESHOLD,
                "passed": consistency_pass,
            },
        },
        "critical_issues": critical_issues,
        "blocking_reason": None
        if validation_passed
        else _get_blocking_reason(
            quality_pass, completeness_pass, consistency_pass, critical_issues
        ),
    }

    return [result]


def _get_blocking_reason(quality_pass, completeness_pass, consistency_pass, critical_issues):
    """Generate human-readable blocking reason."""
    reasons = []
    if not quality_pass:
        reasons.append("Quality score below threshold")
    if not completeness_pass:
        reasons.append("Completeness below threshold")
    if not consistency_pass:
        reasons.append("Consistency below threshold")
    if critical_issues:
        reasons.append(f"{len(critical_issues)} critical issues detected")
    return "; ".join(reasons)
