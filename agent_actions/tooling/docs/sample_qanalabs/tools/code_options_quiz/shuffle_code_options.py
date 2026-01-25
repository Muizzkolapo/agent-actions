import random
from typing import Any, Dict, List
from agent_actions import udf_tool


@udf_tool()
def shuffle_code_options(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Randomize the order of code options (A, B, C, D) and track the correct answer.

    Args:
        data: Dictionary with optimal_code and alternative_code_1/2/3

    Returns:
        List with shuffled options and updated answer key
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Extract the code options
    optimal_code = content.get('optimal_code', '')
    alt_1 = content.get('alternative_code_1', '')
    alt_2 = content.get('alternative_code_2', '')
    alt_3 = content.get('alternative_code_3', '')

    # Create options list with markers
    options = [
        {'code': optimal_code, 'is_correct': True},
        {'code': alt_1, 'is_correct': False},
        {'code': alt_2, 'is_correct': False},
        {'code': alt_3, 'is_correct': False}
    ]

    # Shuffle the options
    random.shuffle(options)

    # Map to letters A, B, C, D
    letters = ['A', 'B', 'C', 'D']
    correct_answer_letter = None

    result = content.copy()
    for i, option in enumerate(options):
        letter = letters[i]
        result[f'option_{letter.lower()}_code'] = option['code']
        if option['is_correct']:
            correct_answer_letter = letter

    result['correct_answer_letter'] = correct_answer_letter

    return [result]
