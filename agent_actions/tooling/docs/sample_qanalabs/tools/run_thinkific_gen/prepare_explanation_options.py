"""
Prepare options for explanation display.

This UDF creates plain-text versions of code options for use in explanations,
while preserving the original VS Code mockup HTML for the quiz options.

Separation of concerns:
- Quiz options: Keep VS Code mockup HTML for beautiful display
- Explanation options: Extract plain code for clear explanation
"""

import re
from typing import Any, Dict, List
from agent_actions import udf_tool


def extract_code_from_vscode_mockup(html: str) -> str:
    """
    Extract plain code from VS Code mockup HTML.

    Returns a simple <pre><code> block suitable for explanations.
    """
    if not html:
        return ''

    # Check if this is a VS Code mockup
    if '<div style="width: 100%;' not in html or 'background: #1e1e1e' not in html:
        # Not a VS Code mockup, return as-is
        return html

    # Extract code content from <code> tags
    code_match = re.search(r'<code[^>]*>(.*?)</code>', html, re.DOTALL)
    if not code_match:
        # Fallback: strip all HTML tags
        clean = re.sub(r'<[^>]+>', '', html)
        clean = clean.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        return clean.strip()

    code_content = code_match.group(1)

    # Remove span tags but keep content
    code_content = re.sub(r'<span[^>]*>', '', code_content)
    code_content = re.sub(r'</span>', '', code_content)

    # Decode HTML entities
    code_content = code_content.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')

    # Wrap in simple, clean code block for explanations
    return f'<pre style="background: #f3f4f6; padding: 12px; border-radius: 6px; overflow-x: auto; font-family: monospace; font-size: 13px; margin: 8px 0; border: 1px solid #e5e7eb;"><code>{code_content.strip()}</code></pre>'


@udf_tool()
def prepare_explanation_options(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Create plain-text versions of options for explanation display.

    Input: Quiz data with VS Code mockup HTML in options
    Output: Same data with additional fields:
        - options_for_quiz: Original VS Code mockups (unchanged)
        - options_for_explanation: Plain code blocks
        - correct_answers_for_explanation: Plain code in correct answers
        - distractors_for_explanation: Plain code in distractors

    This allows:
    - Quiz display: Beautiful VS Code mockups
    - Explanation display: Simple, readable code
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    result = content.copy()

    # Process options array
    if 'options' in content and isinstance(content['options'], list):
        options_for_quiz = content['options']  # Keep original
        options_for_explanation = []

        for option in options_for_quiz:
            if isinstance(option, str):
                plain_code = extract_code_from_vscode_mockup(option)
                options_for_explanation.append(plain_code)
            else:
                options_for_explanation.append(option)

        result['options_for_quiz'] = options_for_quiz
        result['options_for_explanation'] = options_for_explanation
        # Keep 'options' as original for backward compatibility
        result['options'] = options_for_quiz

    # Process correct_answers array
    if 'correct_answers' in content and isinstance(content['correct_answers'], list):
        correct_answers_for_explanation = []

        for answer in content['correct_answers']:
            if isinstance(answer, dict):
                answer_copy = answer.copy()
                if 'option' in answer_copy:
                    answer_copy['option_plain'] = extract_code_from_vscode_mockup(answer_copy['option'])
                correct_answers_for_explanation.append(answer_copy)
            else:
                correct_answers_for_explanation.append(answer)

        result['correct_answers_for_explanation'] = correct_answers_for_explanation

    # Process distractors array
    if 'distractors' in content and isinstance(content['distractors'], list):
        distractors_for_explanation = []

        for distractor in content['distractors']:
            if isinstance(distractor, dict):
                distractor_copy = distractor.copy()
                if 'option' in distractor_copy:
                    distractor_copy['option_plain'] = extract_code_from_vscode_mockup(distractor_copy['option'])
                distractors_for_explanation.append(distractor_copy)
            else:
                distractors_for_explanation.append(distractor)

        result['distractors_for_explanation'] = distractors_for_explanation

    return [result]


if __name__ == "__main__":
    # Test the function
    test_data = {
        'options': [
            '<div style="width: 100%; max-width: 900px; margin: 10px auto; background: #1e1e1e !important;"><code>SELECT * FROM users</code></div>',
            'Plain text option'
        ],
        'correct_answers': [
            {
                'option': '<div style="width: 100%;"><code>def foo():\n    return True</code></div>',
                'explanation_why_it_is_correct': 'This is correct'
            }
        ],
        'distractors': [
            {
                'option': '<div style="width: 100%;"><code>def bar():\n    return False</code></div>',
                'explanation_why_it_is_incorrect': 'This is wrong'
            }
        ]
    }

    result = prepare_explanation_options(test_data)
    print("Original options:", result[0]['options_for_quiz'][0][:50])
    print("Plain options:", result[0]['options_for_explanation'][0][:50])
    print("Correct answer plain:", result[0]['correct_answers_for_explanation'][0]['option_plain'][:50])
    print("Distractor plain:", result[0]['distractors_for_explanation'][0]['option_plain'][:50])
