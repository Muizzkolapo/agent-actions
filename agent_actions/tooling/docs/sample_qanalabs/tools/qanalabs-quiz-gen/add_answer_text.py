from typing import Any, Dict, List
from agent_actions import udf_tool


@udf_tool()
def add_answer_text(question_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add answer_text as a list of the correct option text(s).
    Supports single answer ("A") and multiple answers ("A,C" or "AC").
    Also forwards all fields from previous action.
    """
    if not isinstance(question_data, dict):
        return question_data

    # Handle content wrapper
    if 'content' in question_data:
        content = question_data['content']
    else:
        content = question_data

    answer = str(content.get("answer", "")).strip()
    options = content.get("options", [])

    # Compute answer_text
    answer_texts: List[str] = []
    if answer and isinstance(options, list) and options:
        if "," in answer:
            letters = [a.strip().upper() for a in answer.split(",") if a.strip()]
        else:
            letters = [a.upper() for a in answer if a.isalpha()]

        indices = [ord(letter) - ord("A") for letter in letters]

        seen = set()
        for i in indices:
            if 0 <= i < len(options) and i not in seen:
                seen.add(i)
                answer_texts.append(options[i])

    # Build result with ALL fields forwarded
    result = content.copy()
    result["answer_text"] = answer_texts

    return result
