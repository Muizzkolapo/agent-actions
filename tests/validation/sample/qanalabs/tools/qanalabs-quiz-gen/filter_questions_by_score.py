from typing import Any, List, TypedDict
from agent_actions import udf_tool


class FilterQuestionsByScoreInput(TypedDict, total=False):
    """Input schema for filterquestionsbyscore function."""

    syllabus_alignment_score: int
    question: str
    aligned_skill_area: str
    objective_tested: str
    reasoning: str
    answer: str
    answer_explanation: str
    options: List[str]
    # Distractor fields from sequential generation
    answer_text: List[str]  # Always a list
    distractor_1: str
    explanation_why_it_is_incorrect_1: str
    distractor_2: str
    explanation_why_it_is_incorrect_2: str
    distractor_3: str
    explanation_why_it_is_incorrect_3: str


@udf_tool(input_type=FilterQuestionsByScoreInput)
def filter_questions_by_score(question_data: dict) -> dict:
    """
    Mark questions with a status based on syllabus alignment score.

    Does NOT remove questions - just adds a question_status field:
    - "KEEP" if syllabus_alignment_score >= 80
    - "FILTER" if syllabus_alignment_score < 80

    Args:
        question_data: Dictionary containing question and syllabus_alignment_score

    Returns:
        Original data with added question_status field
    """
    # Get the alignment score
    alignment_score = question_data.get("syllabus_alignment_score", 0)

    # Quality threshold based on objective alignment scoring
    # Questions must score >= 85 to clearly test specific learning objectives
    QUALITY_THRESHOLD = 85

    # Determine status based on score
    if alignment_score >= QUALITY_THRESHOLD:
        question_status = "KEEP"
        status_reason = f"Score {alignment_score}/100 meets threshold ({QUALITY_THRESHOLD})"
    else:
        question_status = "FILTER"
        status_reason = f"Score {alignment_score}/100 below threshold ({QUALITY_THRESHOLD})"

    # Add status field to the data
    question_data["question_status"] = question_status
    question_data["status_reason"] = status_reason

    # Log the status
    question_text = question_data.get("question", "")[:80]
    aligned_skill = question_data.get("aligned_skill_area", "Unknown")

    if question_status == "KEEP":
        print(f"✅ KEEP (score: {alignment_score}) - {aligned_skill}: {question_text}...")
    else:
        print(f"❌ FILTER (score: {alignment_score}) - {aligned_skill}: {question_text}...")

    return question_data
