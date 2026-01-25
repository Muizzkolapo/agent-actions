from typing import Any, Dict
from agent_actions import udf_tool


@udf_tool()
def filter_questions_by_score(question_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add question_status based on syllabus_alignment_score.
    KEEP if score >= 85, else FILTER.
    """
    if not isinstance(question_data, dict):
        return question_data

    alignment_score = question_data.get("syllabus_alignment_score", 0)
    threshold = 85

    if alignment_score >= threshold:
        question_data["question_status"] = "KEEP"
        question_data["status_reason"] = f"Score {alignment_score}/100 meets threshold ({threshold})"
    else:
        question_data["question_status"] = "FILTER"
        question_data["status_reason"] = f"Score {alignment_score}/100 below threshold ({threshold})"

    return question_data
