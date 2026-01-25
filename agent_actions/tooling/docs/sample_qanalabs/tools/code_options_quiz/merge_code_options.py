from typing import Any, Dict, List
from agent_actions import udf_tool
import random


@udf_tool()
def merge_code_options(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Merge optimal code with alternatives into options_combined format.

    Similar to merge_correct_answer_with_distractors but for code options.

    Args:
        data: Dictionary with optimal_code and alternative_code_1,2,3

    Returns:
        List with single record containing options_combined and formatted fields
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Extract code options
    optimal_code = content.get('optimal_code', '')
    alt_1 = content.get('alternative_code_1', '')
    alt_2 = content.get('alternative_code_2', '')
    alt_3 = content.get('alternative_code_3', '')

    # Get explanations
    issue_1 = content.get('issue_description_1', '')
    issue_2 = content.get('issue_description_2', '')
    issue_3 = content.get('issue_description_3', '')

    # Build options list with metadata
    all_options = [
        {
            'code': optimal_code,
            'is_correct': True,
            'explanation': 'This is the optimal implementation following best practices.'
        },
        {
            'code': alt_1,
            'is_correct': False,
            'explanation': issue_1
        },
        {
            'code': alt_2,
            'is_correct': False,
            'explanation': issue_2
        },
        {
            'code': alt_3,
            'is_correct': False,
            'explanation': issue_3
        }
    ]

    # Shuffle options
    random.shuffle(all_options)

    # Build options_combined in qanalabs format
    options_combined = []
    options = []
    answer_letters = []

    for i, opt in enumerate(all_options):
        letter = chr(65 + i)  # A, B, C, D

        # Add to simple options list
        options.append(opt['code'])

        # Track correct answer
        if opt['is_correct']:
            answer_letters.append(letter)

        # Build options_combined entry
        options_combined.append({
            'option': opt['code'],
            'answer_or_distractor': 'answer' if opt['is_correct'] else 'distractor',
            'explanation_why_it_is_correct_or_incorrect': opt['explanation']
        })

    # Build question text
    scenario = content.get('sample_usage_scenario', '')
    considerations = content.get('key_considerations', '')
    question_text = f"{scenario}\n\n{considerations}\n\nWhich implementation should you use?"

    # Forward all fields and add structured output
    result = content.copy()
    result.update({
        'question': question_text,
        'options': options,
        'options_combined': options_combined,
        'answer': answer_letters,
        'question_type': 'SA',  # Single answer for code quizzes
        'correct_answers': [
            {
                'option': opt['code'],
                'explanation_why_it_is_correct': opt['explanation']
            }
            for opt in all_options if opt['is_correct']
        ],
        'distractors': [
            {
                'option': opt['code'],
                'explanation_why_it_is_incorrect': opt['explanation']
            }
            for opt in all_options if not opt['is_correct']
        ]
    })

    return [result]
