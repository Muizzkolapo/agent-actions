from typing import Any, Dict, List
from agent_actions import udf_tool


@udf_tool()
def format_code_options_quiz(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Format code options quiz for Thinkific with syntax highlighting.

    Args:
        data: Quiz data with scenario, options, and explanations

    Returns:
        List with formatted quiz ready for export
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Build formatted question
    scenario = content.get('sample_usage_scenario', '')
    considerations = content.get('key_considerations', '')

    question_text = f"{scenario}\n\n{considerations}\n\nWhich implementation should you use?"

    # Build formatted options with syntax highlighting
    options = []
    for letter in ['a', 'b', 'c', 'd']:
        code = content.get(f'option_{letter}_code', '')
        if code:
            # Wrap in code block for syntax highlighting
            formatted_code = f"```\n{code}\n```"
            options.append(formatted_code)

    # Get correct answer and explanations
    correct_answer = content.get('correct_answer_letter', 'A')

    result = content.copy()
    result.update({
        'question': question_text,
        'options': options,
        'answer': correct_answer,
        'formatted_for_lms': True
    })

    return [result]
