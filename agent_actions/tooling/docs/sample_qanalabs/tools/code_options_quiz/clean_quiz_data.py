"""
Clean and structure quiz data for LMS loading.
This script transforms raw quiz data into a clean, LMS-ready format.
"""

import json
from typing import Dict, Any
from agent_actions import udf_tool


# =============================================================================
# SYNTAX HIGHLIGHTING COLOR CONFIGURATION (Dark Teal & Amber Theme)
# =============================================================================
# 🎨 EASY COLOR CUSTOMIZATION
#
# Edit the colors below to change the quiz theme without touching the code.
# All colors use Tailwind CSS color palette (https://tailwindcss.com/docs/customizing-colors)
#
# Example: To change comments from grey to green:
#   'comment': '#94a3b8',  →  'comment': '#22c55e',
#
# Color format: Use hex codes (e.g., '#5eead4') or CSS gradients
# =============================================================================

SYNTAX_COLORS = {
    # Code element colors
    'comment': '#94a3b8',      # slate-400 - Greyed out comments
    'command': '#5eead4',      # teal-300 - Commands (dbt, run, test, build)
    'flag': '#5eead4',         # teal-300 - Flags (--select, --defer, --state)
    'variable': '#5eead4',     # teal-300 - Variables (modified_models, state_path)
    'keyword': '#5eead4',      # teal-300 - Keywords (all, modified, incremental)
    'path': '#fdba74',         # orange-300 - Paths (path/to/prod/artifacts)
    'string': '#fdba74',       # orange-300 - Strings
    'operator': '#f1f5f9',     # slate-100 - Operators (+, *, :)
    'default': '#f1f5f9',      # slate-100 - Default text
}

# Background and UI colors
UI_COLORS = {
    # Question backgrounds
    'question_container': 'linear-gradient(to bottom right, #0f172a, #134e4a)',  # slate-900 to teal-900
    'scenario_card': 'rgba(30, 41, 59, 0.5)',       # slate-800 with 50% opacity
    'question_code_bg': 'rgba(2, 6, 23, 0.6)',      # slate-950 with 60% opacity

    # Option backgrounds
    'option_gradient': 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #134e4a 100%)',  # slate-900 → slate-800 → teal-900
    'option_header_bg': 'rgba(15, 23, 42, 0.8)',    # slate-900 with 80% opacity
    'option_header_text': '#5eead4',                # teal-300

    # Borders and accents
    'code_border': 'rgba(20, 184, 166, 0.2)',       # teal-500 with 20% opacity
    'instruction_button': 'linear-gradient(to right, #f59e0b, #f97316)',  # amber-500 to orange-500
}
# =============================================================================


def clean_quiz_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean and restructure quiz data for LMS compatibility.

    Args:
        raw_data: Raw quiz data dictionary (flat structure with all fields at top level)

    Returns:
        Cleaned and structured quiz data ready for LMS loading
    """
    # Extract and clean core quiz information
    cleaned_data = {
        # Quiz Identification
        'quiz_id': raw_data.get('id'),
        'source_url': raw_data.get('url'),

        # Quiz Metadata
        'topic': raw_data.get('topic'),
        'difficulty_level': raw_data.get('scenario_complexity'),
        'bloom_taxonomy_details': raw_data.get('bloom_details'),

        # Question and Answer Explanation (from generate_scenario_question action)
        'question': raw_data.get('question'),
        'answer_explanation': raw_data.get('answer_explanation'),

        # Scenario Information (used if question not provided)
        'usage_scenario': raw_data.get('sample_usage_scenario') or raw_data.get('usage_scenario'),
        'scenario_code': raw_data.get('code_for_scenario'),
        'key_considerations': raw_data.get('key_considerations'),

        # Correct Answer (Optimal Code)
        'correct_answer': {
            'code': raw_data.get('optimal_code')
        },

        # Alternative Options (Incorrect Answers)
        'incorrect_options': [
            {
                'option_number': 1,
                'code': raw_data.get('alternative_code_1'),
                'issue_type': raw_data.get('issue_type_1'),
                'issue_description': raw_data.get('issue_description_1')
            },
            {
                'option_number': 2,
                'code': raw_data.get('alternative_code_2'),
                'issue_type': raw_data.get('issue_type_2'),
                'issue_description': raw_data.get('issue_description_2')
            },
            {
                'option_number': 3,
                'code': raw_data.get('alternative_code_3'),
                'issue_type': raw_data.get('issue_type_3'),
                'issue_description': raw_data.get('issue_description_3')
            }
        ],

        # Reference Content
        'reference_content': raw_data.get('page_content')
    }

    # Remove None values from incorrect_options
    cleaned_data['incorrect_options'] = [
        opt for opt in cleaned_data['incorrect_options']
        if opt['code'] is not None
    ]

    return cleaned_data


def format_question_text(question: str) -> str:
    """
    Format question text with proper HTML styling.
    Converts markdown code blocks (```...```) to styled HTML code blocks.
    Adds proper spacing and visual hierarchy.

    Args:
        question: Raw question text with markdown formatting

    Returns:
        HTML-formatted question with styled code blocks
    """
    import re

    if not question or not question.strip():
        return ""

    # Handle explicit markdown code blocks (```...```)
    code_block_pattern = r'```([^`]*?)```'
    parts = []
    last_end = 0

    for match in re.finditer(code_block_pattern, question, re.DOTALL):
        # Add text before code block
        text_before = question[last_end:match.start()].strip()
        if text_before:
            parts.append({
                'type': 'text',
                'content': text_before
            })

        # Add code block
        code_content = match.group(1).strip()
        parts.append({
            'type': 'code',
            'content': code_content
        })

        last_end = match.end()

    # Add remaining text
    text_after = question[last_end:].strip()
    if text_after:
        parts.append({
            'type': 'text',
            'content': text_after
        })

    # Build HTML with enhanced styling
    html_parts = []
    scenario_parts = []
    code_parts = []
    instruction_parts = []

    # Separate parts into scenario, code, and instruction
    for part in parts:
        if part['type'] == 'text':
            lines = [line.strip() for line in part['content'].split('\n') if line.strip()]

            for line in lines:
                # Check if it's an instruction line (contains "Select")
                if 'Select' in line and 'implementation' in line:
                    instruction_parts.append(line)
                else:
                    scenario_parts.append(line)
        elif part['type'] == 'code':
            code_parts.append(part['content'])

    # Build scenario section with card elevation
    if scenario_parts:
        scenario_html = '\n'.join([f'''
        <p style="
            margin: 8px 0;
            line-height: 1.8;
            color: {SYNTAX_COLORS["default"]};
            font-size: 14px;
        ">{line}</p>
        ''' for line in scenario_parts])

        html_parts.append(f'''
        <div style="
            background: {UI_COLORS["scenario_card"]};
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
            margin-bottom: 16px;
        ">
            {scenario_html}
        </div>
        ''')

    # Build code blocks with indentation and deeper elevation
    for code_content in code_parts:
        code_lines = code_content.split('\n')
        cleaned_lines = [line.lstrip() for line in code_lines]
        cleaned_code = '\n'.join(cleaned_lines)

        # Apply syntax highlighting to question code blocks too
        highlighted_code = highlight_bash_code(cleaned_code)

        html_parts.append(f'''
        <div style="
            margin: 16px 24px;
            background: {UI_COLORS["question_code_bg"]};
            border: 1px solid {UI_COLORS["code_border"]};
            border-radius: 6px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        ">
            <pre style="
                background: transparent;
                padding: 16px;
                margin: 0;
                font-family: 'Fira Code', 'JetBrains Mono', 'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace;
                font-size: 13px;
                line-height: 1.6;
                color: {SYNTAX_COLORS["default"]};
                overflow-x: auto;
                white-space: pre;
            "><code>{highlighted_code}</code></pre>
        </div>
        ''')

    # Build instruction section with highest elevation
    if instruction_parts:
        for instruction in instruction_parts:
            html_parts.append(f'''
            <div style="
                margin-top: 24px;
                padding: 12px 16px;
                background: {UI_COLORS["instruction_button"]};
                color: white;
                border-radius: 6px;
                font-weight: 600;
                font-size: 15px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
            ">{instruction}</div>
            ''')

    # Wrap everything in a container
    return f'''<html><body>
    <div style="
        background: {UI_COLORS["question_container"]};
        padding: 24px;
        border-radius: 8px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    ">
        {''.join(html_parts)}
    </div>
    </body></html>'''


def format_explanation_html(explanation: str) -> str:
    """
    Format explanation text with HTML tags for better LMS rendering.
    - Wraps paragraphs in <p> tags
    - Adds <br> at natural break points for long text (>300 chars)
    - Wraps inline code references in <code> tags
    """
    import re

    if not explanation or not isinstance(explanation, str):
        return explanation

    # Skip if already has HTML paragraph tags
    if '<p>' in explanation:
        return explanation

    # Step 1: Wrap inline code references in <code> tags
    # Match backticks first
    explanation = re.sub(r'`([^`]+)`', r'<code>\1</code>', explanation)

    # Then match common code patterns (most specific first to avoid overlaps)
    # Config with value: config.materialized:incremental
    explanation = re.sub(r'\b(config\.[\w.]+:\w+)', r'<code>\1</code>', explanation)
    # State selectors: state:modified+, state:old
    explanation = re.sub(r'\b(state:\w+\+?)', r'<code>\1</code>', explanation)
    # Flags: --select, --defer, etc.
    explanation = re.sub(r'(--[\w-]+)', r'<code>\1</code>', explanation)
    # Single config references: config.materialized (if not already wrapped)
    explanation = re.sub(r'(?<!<code>)(?<!:)\b(config\.[\w.]+)(?!:)(?!</code>)', r'<code>\1</code>', explanation)
    # DBT variables: is_incremental, on_schema_change
    explanation = re.sub(r"(?<!['\w])\b(is_incremental|on_schema_change)(?!['\w])", r'<code>\1</code>', explanation)
    # Standalone materialized (only if not part of config.)
    explanation = re.sub(r"(?<![.\w])(materialized)='(\w+)'", r"<code>\1</code>='\2'", explanation)

    # Step 2: Split text into sentences
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-Z])'
    sentences = re.split(sentence_pattern, explanation)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 1:
        # Single sentence - just wrap it
        return f"<p>{explanation}</p>"

    # Step 3: Build paragraphs with smart breaks
    formatted_parts = []
    current_paragraph = []

    for i, sentence in enumerate(sentences):
        should_break_paragraph = False

        # Rule 1: Question sentences after initial context get their own paragraph
        if i > 0 and '?' in sentence:
            should_break_paragraph = True

        # Rule 2: Sentences starting with "This" or "It" after long paragraph (context shift)
        if i > 0 and current_paragraph:
            if re.match(r'^(This|It|That)\s', sentence):
                if len(' '.join(current_paragraph)) > 150:
                    should_break_paragraph = True

        # Rule 3: Very long accumulated paragraphs (>250 chars)
        if current_paragraph and len(' '.join(current_paragraph)) > 250:
            should_break_paragraph = True

        if should_break_paragraph and current_paragraph:
            paragraph_text = ' '.join(current_paragraph)
            formatted_parts.append(f"<p>{paragraph_text}</p>")
            current_paragraph = [sentence]
        else:
            current_paragraph.append(sentence)

    # Add remaining paragraph
    if current_paragraph:
        paragraph_text = ' '.join(current_paragraph)
        formatted_parts.append(f"<p>{paragraph_text}</p>")

    result = '\n'.join(formatted_parts)

    # Step 4: For very long text without natural breaks, add <br> at semicolons
    if len(explanation) > 300 and ';' in explanation and '<br>' not in result:
        # Add line break after semicolons in long explanations
        result = result.replace('; ', ';<br>')

    return result


def highlight_bash_code(code: str) -> str:
    """Apply syntax highlighting to bash/dbt code using regex with Dark Teal & Amber theme."""
    import re

    # Escape HTML first
    code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Dark Teal & Amber color scheme (Tailwind colors)
    # Step 1: Extract and protect comments from other patterns
    comment_placeholder = "___COMMENT_PLACEHOLDER_{}___ "
    comments = []

    def save_comment(match):
        comments.append(match.group(1))
        return comment_placeholder.format(len(comments) - 1)

    code = re.sub(r'(#.*?)$', save_comment, code, flags=re.MULTILINE)

    # Step 2: Apply syntax highlighting to non-comment code
    # Commands (dbt, run, test, build, etc.)
    code = re.sub(
        r'\b(dbt|run|test|build|compile|snapshot|seed|debug|deps|clean|source|docs|list)\b',
        rf'<span style="color: {SYNTAX_COLORS["command"]};">\1</span>',
        code
    )

    # Flags (--select, --state, --defer, --models, etc.)
    code = re.sub(
        r'(--[\w-]+)',
        rf'<span style="color: {SYNTAX_COLORS["flag"]};">\1</span>',
        code
    )

    # Paths (path/to/something) - BEFORE selectors to avoid conflicts
    code = re.sub(
        r'([\w/.-]+/[\w/.-]+)',
        rf'<span style="color: {SYNTAX_COLORS["path"]};">\1</span>',
        code
    )

    # Selectors with colon (state:modified+, result:error+, etc.)
    code = re.sub(
        r'\b([\w_]+)(:)([\w+]+)',
        rf'<span style="color: {SYNTAX_COLORS["keyword"]};">\1</span><span style="color: {SYNTAX_COLORS["operator"]};">:</span><span style="color: {SYNTAX_COLORS["string"]};">\3</span>',
        code
    )

    # Variables/arguments (modified_models, state_path, etc.)
    code = re.sub(
        r'\b([a-z_]+_[a-z_]+)\b',
        rf'<span style="color: {SYNTAX_COLORS["variable"]};">\1</span>',
        code
    )

    # Special keywords (all, modified, incremental, etc.)
    code = re.sub(
        r'\b(all|modified|incremental|table|view|ephemeral|snapshot)\b',
        rf'<span style="color: {SYNTAX_COLORS["keyword"]};">\1</span>',
        code
    )

    # Plus signs and operators
    code = re.sub(
        r'([+*])',
        rf'<span style="color: {SYNTAX_COLORS["operator"]};">\1</span>',
        code
    )

    # Step 3: Restore comments as uniformly grey (no highlighting inside)
    for i, comment in enumerate(comments):
        placeholder = comment_placeholder.format(i)
        code = code.replace(placeholder, f'<span style="color: {SYNTAX_COLORS["comment"]};">{comment}</span>')

    return code


def format_code_option(code: str) -> str:
    """
    Format code as a clean IDE-style code block with syntax highlighting.

    Args:
        code: Raw code string

    Returns:
        HTML-wrapped code with IDE-style formatting and syntax highlighting
    """
    if not code or not code.strip():
        return ""

    # Strip leading/trailing whitespace from entire block
    code = code.strip()

    # Strip leading whitespace from each line individually
    lines = code.split('\n')
    cleaned_lines = [line.lstrip() for line in lines]
    cleaned_code = '\n'.join(cleaned_lines)

    # Detect language
    if 'dbt' in cleaned_code or any(cmd in cleaned_code for cmd in ['--select', '--models', '--state']):
        lang_label = 'bash'
        highlighted_code = highlight_bash_code(cleaned_code)
    elif 'def ' in cleaned_code or 'import ' in cleaned_code or 'class ' in cleaned_code:
        lang_label = 'python'
        highlighted_code = cleaned_code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    elif any(sql_kw in cleaned_code.lower() for sql_kw in ['select', 'from', 'where', 'join', 'config(']):
        lang_label = 'sql'
        highlighted_code = cleaned_code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    else:
        lang_label = 'bash'
        highlighted_code = highlight_bash_code(cleaned_code)

    return f"""<html><body>
<div style="
    background: {UI_COLORS["option_gradient"]};
    border: 1px solid {UI_COLORS["code_border"]};
    border-radius: 6px;
    padding: 0;
    margin: 8px 0;
    min-height: 220px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
">
    <div style="
        background: {UI_COLORS["option_header_bg"]};
        padding: 8px 16px;
        border-bottom: 1px solid {UI_COLORS["code_border"]};
        border-radius: 6px 6px 0 0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        font-size: 11px;
        color: {UI_COLORS["option_header_text"]};
        letter-spacing: 0.5px;
        flex-shrink: 0;
    ">{lang_label}</div>
    <pre style="
        background: transparent;
        padding: 16px;
        margin: 0;
        font-family: 'Fira Code', 'JetBrains Mono', 'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace;
        font-size: 13px;
        line-height: 1.6;
        color: {SYNTAX_COLORS["default"]};
        overflow-x: auto;
        white-space: pre;
        tab-size: 4;
        flex: 1;
    "><code>{highlighted_code}</code></pre>
</div>
</body></html>"""


@udf_tool
def format_for_lms(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format cleaned data specifically for LMS import with flat structure.
    Randomizes option order and uses upstream question and answer_explanation.

    Args:
        raw_data: Raw quiz data

    Returns:
        LMS-formatted quiz data with question, options, answer, and explanation at same level
    """
    import random

    cleaned_data = clean_quiz_data(raw_data)

    # Use question from upstream generate_scenario_question action if available
    # Otherwise fall back to manual construction
    if cleaned_data.get('question'):
        question_text = cleaned_data['question']
        # Add instruction line if not already present
        if 'Select the optimal code implementation' not in question_text and 'Select' not in question_text:
            question_text += "\n\nSelect the optimal code implementation."
    else:
        # Fallback: Build question text with scenario
        question_text = f"{cleaned_data['usage_scenario']}\n\n"
        if cleaned_data['scenario_code']:
            question_text += f"```\n{cleaned_data['scenario_code']}\n```\n\n"
        question_text += f"{cleaned_data['key_considerations']}\n\nSelect the optimal code implementation."

    # Format question text with HTML styling if not already formatted
    if not question_text.startswith('<html>'):
        question_text = format_question_text(question_text)

    # Prepare all code options (1 correct + N incorrect)
    all_options = []

    # Add correct answer with marker
    all_options.append({
        'code': cleaned_data['correct_answer']['code'],
        'is_correct': True,
        'original_index': 0
    })

    # Add incorrect options with markers
    for idx, incorrect_opt in enumerate(cleaned_data['incorrect_options']):
        all_options.append({
            'code': incorrect_opt['code'],
            'is_correct': False,
            'original_index': idx + 1,
            'issue_type': incorrect_opt['issue_type'],
            'issue_description': incorrect_opt['issue_description']
        })

    # Randomize option order
    random.shuffle(all_options)

    # Format options and find correct answer position
    formatted_options = []
    correct_answer_index = None
    option_labels = ['A', 'B', 'C', 'D', 'E', 'F']  # Support up to 6 options

    for idx, opt in enumerate(all_options):
        formatted_options.append(format_code_option(opt['code']))
        if opt['is_correct']:
            correct_answer_index = idx

    # Answer key - the letter of the correct option after randomization
    answer = option_labels[correct_answer_index]

    # Use answer_explanation from upstream generate_scenario_question action if available
    # Otherwise create a simple explanation
    if cleaned_data.get('answer_explanation'):
        explanation = cleaned_data['answer_explanation']
    else:
        # Fallback: Build basic explanation
        explanation = f"The correct answer is Option {answer}. This implementation is optimal because it follows best practices and avoids common issues."

    # Build options_combined array with explanations
    options_combined = []
    correct_answers = []
    distractors = []

    for idx, opt in enumerate(all_options):
        option_label = option_labels[idx]
        formatted_option = formatted_options[idx]

        if opt['is_correct']:
            # Correct answer - format explanation with HTML
            formatted_explanation = format_explanation_html(explanation)
            option_entry = {
                'option': opt['code'],
                'answer_or_distractor': 'answer',
                'explanation_why_it_is_correct_or_incorrect': formatted_explanation
            }
            correct_answers.append({
                'option': opt['code'],
                'explanation_why_it_is_correct': formatted_explanation
            })
        else:
            # Distractor - format explanation with HTML
            formatted_issue_desc = format_explanation_html(opt['issue_description'])
            option_entry = {
                'option': opt['code'],
                'answer_or_distractor': 'distractor',
                'explanation_why_it_is_correct_or_incorrect': formatted_issue_desc
            }
            distractors.append({
                'option': opt['code'],
                'explanation_why_it_is_incorrect': formatted_issue_desc
            })

        options_combined.append(option_entry)

    # Build combined_explanation in markdown format with HTML-formatted explanations
    combined_explanation = f"## Correct Answer:\n**Option:** {correct_answers[0]['option']}\n\n{correct_answers[0]['explanation_why_it_is_correct']}\n\n"
    combined_explanation += "## Incorrect Options:\n\n"

    for idx, distractor in enumerate(distractors, 1):
        combined_explanation += f"### Distractor {idx}:\n{distractor['option']}\n\n{distractor['explanation_why_it_is_incorrect']}\n\n"

    # Flat structure - all fields at same level
    lms_format = {
        'quiz_id': cleaned_data['quiz_id'],
        'topic': cleaned_data['topic'],
        'difficulty_level': cleaned_data['difficulty_level'],
        'bloom_taxonomy_details': cleaned_data['bloom_taxonomy_details'],
        'source_url': cleaned_data['source_url'],
        'question': question_text,
        'options': formatted_options,
        'answer': answer,
        'explanation': explanation,  # Keep for backwards compatibility
        'options_combined': options_combined,
        'correct_answers': correct_answers,
        'distractors': distractors,
        'combined_explanation': combined_explanation
    }

    return lms_format


def main():
    """Main execution function with example usage."""
    # Example raw data (you would load this from your source)
    raw_data = {
            "question": "You need to run only modified dbt models in CI to save time. Which implementation should you use?",
            "answer_explanation": "This implementation uses state:modified+ to target only changed models and their downstream dependencies, minimizing unnecessary runs and providing faster CI feedback.",
            "optimal_code": "dbt run --select state:modified+ --defer --state path/to/prod/artifacts",
            "alternative_code_1": "dbt run",
            "issue_type_1": "performance",
            "issue_description_1": "Runs all models instead of just modified ones, causing unnecessary processing overhead.",
            "alternative_code_2": "dbt run -s state:modified+ --state path/to/prod/artifacts",
            "issue_type_2": "reliability",
            "issue_description_2": "Missing --defer flag means upstream models won't use production versions.",
            "alternative_code_3": "dbt run --select state:modified+ --defer",
            "issue_type_3": "configuration",
            "issue_description_3": "Missing --state flag means no comparison state is provided.",
            "sample_usage_scenario": "In a CI workflow, you need to efficiently run only the models that have been modified.",
            "code_for_scenario": "dbt run -s state:modified+ --defer --state path/to/prod/artifacts",
            "scenario_complexity": "intermediate",
            "key_considerations": "Requires state manifest for comparison. The + includes downstream dependencies.",
            "topic": "DBT Analytics Engineering Certification Exam",
            "bloom_details": "Applies dbt concepts in practical scenarios.",
            "id": "ad093b0a-4089-4800-b2b7-a429459640bd",
            "url": "https://docs.getdbt.com/best-practices/best-practice-workflows"
        }

    # Clean the data
    cleaned = clean_quiz_data(raw_data)
    print("Cleaned Data:")
    print(json.dumps(cleaned, indent=2))
    print("\n" + "="*80 + "\n")

    # Format for LMS
    lms_ready = format_for_lms(raw_data)
    print("LMS-Ready Format:")
    print("Question:", lms_ready.get('question', 'N/A')[:100] + "...")
    print("Number of options:", len(lms_ready.get('options', [])))
    print("Correct answer:", lms_ready.get('answer'))
    print("Explanation:", lms_ready.get('explanation', 'N/A')[:100] + "...")

    # Save to file
    with open('cleaned_quiz_data.json', 'w') as f:
        json.dump(cleaned, f, indent=2)

    with open('lms_ready_quiz.json', 'w') as f:
        json.dump(lms_ready, f, indent=2)

    print("\n✓ Data saved to cleaned_quiz_data.json and lms_ready_quiz.json")


if __name__ == "__main__":
    main()
