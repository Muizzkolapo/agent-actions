from typing import Any, Dict, List
from agent_actions import udf_tool


@udf_tool()
def aggregate_answer_votes(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aggregate validator votes for answer predictions.
    Returns votes_summary list with predicted answer and reasoning per validator.
    Also forwards question and distractor fields for downstream actions.
    """
    if not isinstance(data, dict):
        return {"votes_summary": []}

    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    votes: List[Dict[str, Any]] = []
    for i in range(1, 6):
        pred = content.get(f"predicted_answer_{i}", "")
        if pred:
            votes.append({
                "validator": i,
                "predicted": pred,
                "reasoning": content.get(f"reasoning_{i}", ""),
                "quotes": content.get(f"supporting_quotes_{i}", [])
            })

    # Build result with votes_summary AND forwarded fields
    result = {
        "votes_summary": votes,
        # Forward question fields
        "question": content.get("question"),
        "options": content.get("options"),
        "answer": content.get("answer"),
        "answer_explanation": content.get("answer_explanation"),
        "answer_text": content.get("answer_text"),
        # Forward distractor fields
        "distractor_1": content.get("distractor_1"),
        "distractor_2": content.get("distractor_2"),
        "distractor_3": content.get("distractor_3"),
        "explanation_why_it_is_incorrect_1": content.get("explanation_why_it_is_incorrect_1"),
        "explanation_why_it_is_incorrect_2": content.get("explanation_why_it_is_incorrect_2"),
        "explanation_why_it_is_incorrect_3": content.get("explanation_why_it_is_incorrect_3"),
    }

    return result
