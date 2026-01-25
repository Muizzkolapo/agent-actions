import json
import re
import os
import markdown2
import markdown
from html import escape
from typing import Any, Dict, List, TypedDict, Union
from agent_actions import udf_tool


def strip_html_for_explanation(text: str) -> str:
    """
    Strip HTML tags from text for display in explanation section.
    VS Code mockups should show as plain code, not full HTML.
    """
    if not text:
        return ''
    # Check if this looks like a VS Code mockup (has the characteristic div structure)
    if '<div style="width: 100%;' in text and 'background: #1e1e1e' in text:
        # Extract just the code content from inside <code> tags
        code_match = re.search(r'<code[^>]*>(.*?)</code>', text, re.DOTALL)
        if code_match:
            code_content = code_match.group(1)
            # Remove span tags but keep content
            code_content = re.sub(r'<span[^>]*>', '', code_content)
            code_content = re.sub(r'</span>', '', code_content)
            # Decode HTML entities
            code_content = code_content.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            # Wrap in a simple code block for explanation
            return f'<pre style="background: #f3f4f6; padding: 12px; border-radius: 6px; overflow-x: auto; font-family: monospace; font-size: 13px; margin: 8px 0;"><code>{code_content.strip()}</code></pre>'
    # For non-VS Code content, strip all HTML tags
    clean = re.sub(r'<[^>]+>', '', text)
    clean = clean.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return clean.strip()

# Import randomization and MA instruction functions
try:
    from simple_randomize_quiz import process_ma_instructions_only, add_ma_instruction_simple
    from randomize_quiz import randomize_quiz_options
    randomization_available = True
except ImportError:
    # Fallback implementations if modules are not available
    import random
    import hashlib
    import copy

    def process_ma_instructions_only(content):
        return content

    def add_ma_instruction_simple(question_text, question_type, num_correct):
        if question_type != "MA" or num_correct <= 1:
            return question_text

        if num_correct == 2:
            instruction = " <em>(Select 2 options)</em>"
        elif num_correct == 3:
            instruction = " <em>(Select 3 options)</em>"
        elif num_correct == 4:
            instruction = " <em>(Select 4 options)</em>"
        elif num_correct == 5:
            instruction = " <em>(Select 5 options)</em>"
        else:
            instruction = f" <em>(Select {num_correct} options)</em>"

        if '<p>' in question_text and '</p>' in question_text:
            last_p_index = question_text.rfind('</p>')
            return question_text[:last_p_index] + instruction + question_text[last_p_index:]
        else:
            return question_text + instruction

    def get_option_text_simple(option_html):
        """Extract plain text from HTML option for comparison."""
        import re
        text = re.sub(r'<[^>]+>', '', option_html)
        text = ' '.join(text.split())
        return text.strip()

    def should_keep_at_end_simple(option_text):
        """Check if an option should be kept at the end."""
        text_lower = option_text.lower()
        keep_at_end_phrases = [
            'all of the above', 'none of the above', 'all of these', 'none of these',
            'both a and b', 'both b and c', 'both a and c', 'a and b only', 'b and c only', 'a and c only'
        ]
        return any(phrase in text_lower for phrase in keep_at_end_phrases)

    def create_reproducible_shuffle_simple(items_count, seed_string):
        """Create a reproducible shuffle based on a seed string."""
        hash_obj = hashlib.md5(seed_string.encode())
        seed = int(hash_obj.hexdigest()[:8], 16)
        indices = list(range(items_count))
        rng = random.Random(seed)
        rng.shuffle(indices)
        return indices

    def randomize_quiz_options(content, enable_randomization=True):
        """Randomize quiz options while maintaining all data relationships."""
        if not enable_randomization:
            return content

        content = copy.deepcopy(content)
        options = content.get('options', [])

        # Skip if too few options to randomize
        if len(options) < 2:
            return content

        # Get question ID for reproducible randomization
        question_id = content.get('id') or content.get('question_guid') or content.get('guid', 'default')

        # Separate special options that should stay at the end
        special_options = []
        special_indices = []
        regular_options = []
        regular_indices = []

        for i, option in enumerate(options):
            option_text = get_option_text_simple(option)
            if should_keep_at_end_simple(option_text):
                special_options.append(option)
                special_indices.append(i)
            else:
                regular_options.append(option)
                regular_indices.append(i)

        # Create shuffle for regular options only
        if len(regular_options) > 1:
            shuffle_indices = create_reproducible_shuffle_simple(len(regular_options), question_id)
        else:
            shuffle_indices = [0] if regular_options else []

        # Build the final shuffle mapping (old_index -> new_index)
        index_mapping = {}
        new_options = []

        # Add shuffled regular options
        for new_idx, shuffle_idx in enumerate(shuffle_indices):
            if shuffle_idx < len(regular_indices):
                old_idx = regular_indices[shuffle_idx]
                index_mapping[old_idx] = new_idx
                if shuffle_idx < len(regular_options):
                    new_options.append(regular_options[shuffle_idx])

        # Add special options at the end
        for i, special_idx in enumerate(special_indices):
            new_idx = len(new_options)
            index_mapping[special_idx] = new_idx
            new_options.append(special_options[i])

        # Update the options array
        content['options'] = new_options

        # Update answer_indices
        if 'answer_indices' in content:
            old_answer_indices = content['answer_indices']
            new_answer_indices = []
            for old_idx in old_answer_indices:
                if old_idx in index_mapping:
                    new_answer_indices.append(index_mapping[old_idx])
            content['answer_indices'] = sorted(new_answer_indices)

        # Update answer_letter
        if 'answer_indices' in content:
            new_letters = []
            for idx in content['answer_indices']:
                if idx < 26:
                    new_letters.append(chr(ord('A') + idx))
                else:
                    first = idx // 26 - 1
                    second = idx % 26
                    new_letters.append(chr(ord('A') + first) + chr(ord('A') + second))
            content['answer_letter'] = ','.join(new_letters)

        # Update options_combined if it exists
        if 'options_combined' in content:
            old_options_combined = content['options_combined']
            new_options_combined = []

            for new_option in new_options:
                new_option_text = get_option_text_simple(new_option)
                for item in old_options_combined:
                    item_option_text = get_option_text_simple(item.get('option', ''))
                    if item_option_text == new_option_text:
                        new_item = copy.deepcopy(item)
                        new_item['option'] = new_option
                        new_options_combined.append(new_item)
                        break

            content['options_combined'] = new_options_combined

        return content

    randomization_available = False

def format_text_with_newlines(text):
    """
    Helper function to format any text with newlines into properly styled HTML divs.
    """
    if not text:
        return ''
    
    paragraphs = text.split('\n\n')
    formatted_paragraphs = []
    
    for paragraph in paragraphs:
        lines = paragraph.strip().split('\n')
        formatted_lines = []
        for line in lines:
            if not line.strip():
                continue
            formatted_lines.append(f'''
                <div style="
                    padding: 8px 0;
                    color: #374151;
                    font-size: 16px;
                    line-height: 1.6;
                    font-family: 'Nunito', 'Segoe UI', Roboto, sans-serif;
                ">{line.strip()}</div>
            ''')
        formatted_paragraphs.append(''.join(formatted_lines))
    
    return ''.join(formatted_paragraphs)

def render_content(text):
    """Render content - handles both HTML and markdown appropriately"""
    if not text:
        return ""
    
    # Check if text already contains HTML tags
    if '<' in text and '>' in text:
        # Text contains HTML, return as-is (don't process as markdown)
        return text.strip()
    
    # Text appears to be markdown, process it
    return render_markdown_content(text)

def render_markdown_content(text):
    """Render markdown text to HTML with proper code block handling"""
    # Unescape literal "\n" and fix bad formatting
    text = text.replace("\\n", "\n")
    text = text.replace("\\n", "\n")

    # ONLY fix triple backtick code fences (do NOT touch inline `code`)
    # Add newline before ``` if it's not already on its own line
    text = re.sub(r'(?<!\n)(```[a-zA-Z]*)', r'\n\1', text)
    # Add newline after the opening code fence if needed
    text = re.sub(r'(```[a-zA-Z]*)\s*([^\n])', r'\1\n\2', text)
    # Add newline before closing ```
    text = re.sub(r'([^\n])(```)', r'\1\n\2', text)
    return markdown.markdown(
        text.strip(),
        extensions=['extra', 'attr_list', 'fenced_code','codehilite'],
        extension_configs={
            'codehilite': {
                'css_class': 'highlight',
                'guess_lang': False,
                'use_pygments': True,
                'indent_guides': True,
                'pygments_style': 'friendly',
            },
        },
        output_format='html5'
    )

# Keep backward compatibility
def render_markdown(text):
    """Legacy function - use render_content instead"""
    return render_content(text)

def render_code_snippets(code_snippets: List[Dict]) -> str:
    """Render code snippets with proper formatting for concept explanations"""
    if not code_snippets:
        return ""
    
    html_parts = ['<h4 style="color: #374151; margin-bottom: 1rem; font-weight: 600;">💻 Code Examples:</h4>']
    
    for snippet in code_snippets:
        # Handle case where snippet might be a string instead of dict
        if isinstance(snippet, str):
            # Remove backticks if present and use the string as code
            code = snippet.strip('`')
            description = ''
            code_type = 'text'
        elif isinstance(snippet, dict):
            description = snippet.get('description', '')
            code = snippet.get('code', '')
            code_type = snippet.get('type', 'text')
        else:
            print(f"WARNING: Expected dict or string but got {type(snippet)} in code_snippets: {snippet}")
            continue

        if description:
            html_parts.append(f'<p style="color: #6B7280; font-size: 0.9rem; margin-bottom: 0.5rem; font-style: italic;">{description}</p>')

        # Format and escape the code
        formatted_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        html_parts.append(f'''
            <pre style="
                font-family: ui-monospace, 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'SF Mono', 'Consolas', 'Liberation Mono', 'Menlo', Monaco, monospace;
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                color: #e2e8f0;
                padding: 1.25rem;
                border-radius: 8px;
                overflow-x: auto;
                margin-bottom: 1rem;
                font-size: 14px;
                line-height: 1.7;
                border: 1px solid #334155;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                font-variant-ligatures: common-ligatures;
                font-feature-settings: 'liga' 1, 'calt' 1;
                tab-size: 2;
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
            ">{formatted_code}</pre>
        ''')
    
    return ''.join(html_parts)

def get_correct_answers(obj: Dict[str, Any]) -> List[str]:
    """
    Extract correct answer texts for both MA and SA questions.
    Returns list of correct answer option texts.
    """
    # Method 1: Use the new 'answer' field (array format)
    if 'answer' in obj and isinstance(obj['answer'], list):
        answer_field = obj['answer']
        
        # Handle complex format: [["text1", "text2"], "A,B,C"]
        if len(answer_field) == 2 and isinstance(answer_field[0], list):
            return answer_field[0]  # Return the text array
        else:
            return answer_field  # Already a simple array of texts
    
    # Method 2: Use answer_indices to find correct options
    if 'answer_indices' in obj and 'options' in obj:
        indices = obj['answer_indices']
        options = obj['options']
        return [options[i] for i in indices if 0 <= i < len(options)]
    
    # Method 3: Use answer_letter to find correct options
    if 'answer_letter' in obj and 'options' in obj:
        letters = [letter.strip().upper() for letter in obj['answer_letter'].split(',')]
        indices = [ord(letter) - ord('A') for letter in letters if letter]
        options = obj['options']
        return [options[i] for i in indices if 0 <= i < len(options)]
    
    # Method 4: Use single answer_index
    if 'answer_index' in obj and 'options' in obj:
        idx = obj['answer_index']
        options = obj['options']
        if 0 <= idx < len(options):
            return [options[idx]]
    
    # Method 5: Find from options_combined
    correct_answers = []
    for item in obj.get('options_combined', []):
        if item.get('answer_or_distractor') == 'answer':
            correct_answers.append(item.get('option', ''))
    
    return [ans for ans in correct_answers if ans]

def validate_and_clean_answers(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that marked correct answers make logical sense.
    This helps catch data corruption issues.
    """
    # Keywords that should NOT appear in correct answers for security questions
    suspicious_keywords = ['train', 'store', 'internally', 'sensitive', 'memorize', 'embed', 'public']
    
    # Get question context to understand what type of question this is
    question = obj.get('question', '').lower()
    is_security_question = any(keyword in question for keyword in ['security', 'secure', 'api key', 'sensitive', 'crm'])
    
    if is_security_question:
        # For security questions, validate that answers make sense
        correct_answers = get_correct_answers(obj)
        
        # Check if any correct answer contains suspicious content
        suspicious_answers = []
        for answer in correct_answers:
            if any(keyword in answer.lower() for keyword in suspicious_keywords):
                suspicious_answers.append(answer)
        
        if suspicious_answers:
            print(f"WARNING: Security question has suspicious correct answers: {suspicious_answers}")
            print("This might indicate data corruption. Please review manually.")
    
    return obj

def pick_correct_answer_for_thinkific(obj: Dict[str, Any]) -> str:
    """
    Return the correct answer text for Thinkific compatibility.
    For MA questions, returns the first correct answer.
    For SA questions, returns the single correct answer.
    """
    correct_answers = get_correct_answers(obj)
    
    if not correct_answers:
        return ""
    
    # For Thinkific compatibility, return the first correct answer
    # (Thinkific may not support multiple correct answers)
    return correct_answers[0]

def parse_and_style_combined_explanation(combined_text: str) -> str:
    """
    Parse combined_explanation markdown and apply proper styling with dark box for correct answers.
    Handles both SA (single option) and MA (multiple options listed individually).
    """
    if not combined_text:
        return ""
    
    # Convert markdown to HTML
    html_content = render_content(combined_text)
    
    # Check if this is MA by looking for "Correct Answers:" (plural)
    is_ma_question = "Correct Answers:" in html_content
    
    if is_ma_question:
        # MA Question: Handle multiple options listed individually
        # Pattern 1: Handle "Option 1:", "Option 2:", etc. with their content
        html_content = re.sub(
            r'<p><strong>Option \d+:</strong>\s*([^<]+)</p>',
            r'<div class="correct-answer-box">\1</div>',
            html_content
        )
        
        # Pattern 2: Handle any remaining options under "Correct Answers:" section
        # Look for paragraphs that contain option-like content
        html_content = re.sub(
            r'(<h2>Correct Answers:</h2>.*?)<p>((?:Include|Fine-tune|Combine|Implement|Use)[^<]+)</p>',
            r'\1<div class="correct-answer-box">\2</div>',
            html_content,
            flags=re.DOTALL
        )
        
    else:
        # SA Question: Handle single option
        # Pattern 1: Handle the "**Option:**" bold text under "Correct Answer:" section
        html_content = re.sub(
            r'(<h2>Correct Answer:</h2>\s*<p><strong>Option:</strong>\s*)([^<]+)(</p>)',
            r'\1</p><div class="correct-answer-box">\2</div><p>',
            html_content,
            flags=re.DOTALL
        )
        
        # Pattern 2: Alternative - catch the bold Option text in its own paragraph
        html_content = re.sub(
            r'<p><strong>Option:</strong>\s*([^<]+)</p>',
            r'<div class="correct-answer-box">\1</div>',
            html_content
        )
    
    # Common patterns for both SA and MA
    # Pattern 3: Handle distractor option texts under "### Distractor N:" headings - use red styling and remove numbering
    html_content = re.sub(
        r'<h3>Distractor \d+:</h3>\s*<p>([^<]+)</p>',
        r'<div class="incorrect-answer-box">\1</div>',
        html_content
    )
    
    # Pattern 4: Handle any remaining distractor option-like content
    html_content = re.sub(
        r'<p>((?:Configure|Use|Have|Implement|Integrate|Train|Allow|Store|Apply|Fine-tune|Expand|Develop|Switch|Always)[^<]*?(?:trigger|dataset|model|validation|resource|header|credentials)[^<]*)</p>',
        r'<div class="incorrect-answer-box">\1</div>',
        html_content
    )
    
    return html_content

def get_explanation_css() -> str:
    """Return the CSS styles for explanations"""
    return '''
        /* Prevent horizontal scroll/jitter on mobile */
        html, body {
            overflow-x: hidden;
            margin: 0;
            padding: 0;
            background-color: #FFFFFF;
        }

        /* Make sure all elements don't overflow */
        *, *::before, *::after {
            box-sizing: border-box;
            max-width: 100%;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'SF Pro Text', 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
            font-size: 16px;
            line-height: 1.65;
            color: #334155;
            max-width: 850px;
            margin: 0 auto;
            padding: 20px;
            font-weight: 400;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            font-feature-settings: 'kern' 1;
        }

        h1 {
            color: #4F46E5;
            border-bottom: 2px solid #E5E7EB;
            padding-bottom: 10px;
            margin-top: 30px;
        }

        h2 {
            margin-top: 24px;
            color: #1F2937;
            font-size: 1.25rem;
            font-weight: 600;
        }

        h3 {
            margin-top: 20px;
            margin-bottom: 12px;
            color: #6B7280;
            font-size: 1.1rem;
            font-weight: 500;
        }

        /* Question Review Box - Main container */
        .question-review-box {
            margin-bottom: 1.5rem;
            padding: 1.25rem;
            background: #F9FAFB;
            border-radius: 8px;
            border-left: 3px solid #4F46E5;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        /* Labels with icons */
        .question-label,
        .correct-answer-label,
        .explanation-label {
            font-size: 0.9rem;
            color: #6B7280;
            margin-bottom: 0.75rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-weight: 500;
        }

        .correct-answer-label {
            color: #10B981;
            margin-top: 1rem;
        }

        /* Text content */
        .question-text {
            color: #1e293b;
            line-height: 1.65;
            margin-bottom: 1rem;
            font-size: 15px;
            font-weight: 400;
        }

        .correct-answer-text {
            color: #059669;
            margin-left: 1.5rem;
            margin-bottom: 0.5rem;
            line-height: 1.6;
            font-weight: 500;
            font-size: 15px;
        }

        .explanation-text {
            color: #475569;
            line-height: 1.65;
            font-size: 15px;
            font-weight: 400;
        }

        /* Answer boxes for listing options */
        .correct-answer-box {
            margin-bottom: 12px;
            padding: 12px 16px;
            border-radius: 6px;
            background-color: #D1FAE5;
            color: #065F46;
            border: 1px solid #10B981;
            font-size: 0.95rem;
            line-height: 1.5;
            font-weight: 500;
        }

        .incorrect-answer-box {
            margin-bottom: 12px;
            padding: 12px 16px;
            border-radius: 6px;
            background-color: #FEE2E2;
            color: #991B1B;
            border: 1px solid #EF4444;
            font-size: 0.95rem;
            line-height: 1.5;
        }

        .key-points-heading {
            margin-top: 24px;
            color: #EA580C;
            font-size: 1.1rem;
            font-weight: 500;
        }

        .explanation {
            margin-bottom: 20px;
            color: #475569;
        }

        .explanation p {
            margin: 0.6rem 0;
            color: #334155;
            line-height: 1.65;
            font-size: 15px;
        }

        /* Inline code (not inside pre) */
        :not(pre) > code {
            background-color: #F3F4F6;
            color: #1F2937;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'JetBrains Mono', Menlo, Consolas, monospace;
            font-size: 90%;
            word-break: break-word;
            border: 1px solid #E5E7EB;
        }

        /* Block code */
        pre {
            font-family: 'JetBrains Mono', Menlo, Consolas, monospace;
            background-color: #F9FAFB;
            color: #1F2937;
            padding: 12px;
            border-radius: 6px;
            white-space: pre;
            overflow-x: auto;
            display: block;
            margin-bottom: 20px;
            border: 1px solid #E5E7EB;
        }

        /* Ensure nested code in pre doesn't override styles */
        pre code {
            background: none;
            color: inherit;
            padding: 0;
            font-size: 100%;
        }

        .steps {
            background-color: #F9FAFB;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 3px solid #4F46E5;
        }

        .steps ol {
            margin-bottom: 0;
            color: #374151;
        }

        /* Separator lines */
        .separator {
            margin: 1.5rem 0;
            border: 0;
            height: 1px;
            background: #E5E7EB;
        }
    '''

def format_explanation_ma_sa(obj: Dict[str, Any]) -> str:
    """
    Generate explanation HTML that works for both MA and SA questions.
    Now uses the new cleaner data structure with correct_answers array.
    """
    
    # Get the question text to display in the explanation
    question_text = obj.get('question', '')
    
    # Method 1: Use the new data structure with correct_answers array (preferred)
    if 'correct_answers' in obj and obj['correct_answers']:
        return format_explanation_from_correct_answers(obj, question_text)
    
    # Method 2: Use combined_explanation if available (legacy support)
    elif 'combined_explanation' in obj and obj['combined_explanation']:
        combined_text = obj['combined_explanation']
        
        # Parse the combined explanation to apply proper styling
        styled_html = parse_and_style_combined_explanation(combined_text)
        
        # Add question text at the top if not already present
        question_section = ""
        if question_text and question_text not in styled_html:
            question_section = f'''
            <div style="
                background-color: #F8F9FA;
                padding: 16px 20px;
                margin-bottom: 20px;
                border-radius: 8px;
                border: 1px solid #E5E7EB;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            ">
                <div style="
                    display: flex;
                    align-items: flex-start;
                    gap: 12px;
                ">
                    <div style="
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        min-width: 20px;
                        min-height: 20px;
                        padding: 2px;
                        background: #EEF2FF;
                        border: 1px solid #818CF8;
                        border-radius: 4px;
                    ">
                        <span style="font-size: 12px;">❓</span>
                    </div>
                    <div style="flex: 1;">
                        <h4 style="
                            margin: 0 0 8px 0;
                            color: #6B7280;
                            font-size: 11px;
                            font-weight: 600;
                            text-transform: uppercase;
                            letter-spacing: 0.08em;
                        ">Question:</h4>
                        <p style="
                            margin: 0;
                            color: #1F2937;
                            font-size: 14px;
                            line-height: 1.5;
                            font-weight: 400;
                        ">{question_text}</p>
                    </div>
                </div>
            </div>
            '''
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        {get_explanation_css()}
    </style>
</head>
<body>
    {question_section}
    {styled_html}
</body>
</html>'''
    
    # Method 3: Build from options_combined (fallback) with rich styling
    return format_explanation_from_options_combined(obj.get('options_combined', []), question_text)

def format_explanation_from_correct_answers(obj: Dict[str, Any], question_text: str = "") -> str:
    """
    Build explanation HTML from the new data structure with correct_answers array.
    This handles both SA and MA questions cleanly.
    """
    html_parts = [f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        {get_explanation_css()}
    </style>
</head>
<body>
''']

    # Add question text at the top with enhanced card design matching the reference
    if question_text:
        html_parts.append(f'''
        <div style="
            background-color: #F8F9FA;
            padding: 16px 20px;
            margin-bottom: 20px;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        ">
            <div style="
                display: flex;
                align-items: flex-start;
                gap: 12px;
            ">
                <div style="
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    min-width: 20px;
                    min-height: 20px;
                    padding: 2px;
                    background: #EEF2FF;
                    border: 1px solid #818CF8;
                    border-radius: 4px;
                ">
                    <span style="font-size: 12px;">❓</span>
                </div>
                <div style="flex: 1;">
                    <h4 style="
                        margin: 0 0 8px 0;
                        color: #6B7280;
                        font-size: 11px;
                        font-weight: 600;
                        text-transform: uppercase;
                        letter-spacing: 0.08em;
                    ">Question:</h4>
                    <p style="
                        margin: 0;
                        color: #1F2937;
                        font-size: 14px;
                        line-height: 1.5;
                        font-weight: 400;
                    ">{question_text}</p>
                </div>
            </div>
        </div>
        ''')

    # Get correct answers from the new structure
    # Use explanation versions with plain text if available, fallback to original
    correct_answers = obj.get('correct_answers_for_explanation', obj.get('correct_answers', []))
    distractors = obj.get('distractors_for_explanation', obj.get('distractors', []))
    
    # Create question review box with correct answers and explanation
    html_parts.append('<div class="question-review-box">')
    
    # Determine if SA or MA based on number of correct answers
    if len(correct_answers) == 1:
        # SA: Single answer
        html_parts.append('''
            <div class="correct-answer-label">
                <span>✓</span>
                <span>Correct Answer:</span>
            </div>
        ''')
        answer = correct_answers[0]
        # Use plain-text option if available (from prepare_explanation_options)
        option_display = answer.get("option_plain", answer["option"])
        html_parts.append(f'<div class="correct-answer-text">{option_display}</div>')
        
        # Add explanation within the box
        if answer.get("explanation_why_it_is_correct"):
            html_parts.append('''
                <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #E5E7EB;">
                    <div class="explanation-label">
                        <span style="opacity: 0.7;">📝</span>
                        <span>Explanation:</span>
                    </div>
            ''')
            html_parts.append(f'<div class="explanation-text">{render_content(answer["explanation_why_it_is_correct"])}</div>')
            html_parts.append('</div>')

    elif len(correct_answers) > 1:
        # MA: Multiple answers
        html_parts.append('''
            <div class="correct-answer-label">
                <span>✓</span>
                <span>Correct Answers:</span>
            </div>
        ''')
        
        # Add each correct answer with bullet points
        for answer in correct_answers:
            # Use plain-text option if available (from prepare_explanation_options)
            option_display = answer.get("option_plain", answer["option"])
            html_parts.append(f'<div class="correct-answer-text">• {option_display}</div>')
        
        # Add shared explanation within the box
        if correct_answers and correct_answers[0].get("explanation_why_it_is_correct"):
            html_parts.append('''
                <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #E5E7EB;">
                    <div class="explanation-label">
                        <span style="opacity: 0.7;">📝</span>
                        <span>Explanation:</span>
                    </div>
            ''')
            html_parts.append(f'<div class="explanation-text">{render_content(correct_answers[0]["explanation_why_it_is_correct"])}</div>')
            html_parts.append('</div>')
    
    html_parts.append('</div>')  # Close question-review-box

    # Add Key Points to Remember section (only if flagged_items exists)
    flagged_items = obj.get('flagged_items')
    if flagged_items:
        html_parts.append('<h2 class="key-points-heading">Key Points to Remember:</h2>')
        html_parts.append('<ul>')
        for item in flagged_items:
            if 'fact' in item:
                html_parts.append(f'<li>{item["fact"]}</li>')
        html_parts.append('</ul>')

    # Add incorrect answers (distractors) with improved styling
    if distractors:
        html_parts.append('<div style="margin-top: 2rem; border-top: 1px solid #E5E7EB; padding-top: 1.5rem;">')
        html_parts.append('<h3 style="color: #DC2626; margin-bottom: 1rem;">Incorrect Options:</h3>')
        html_parts.append('<div class="option-explanations">')
        
        for distractor in distractors:
            html_parts.append('<div style="margin-bottom: 1.5rem;">')
            # Use plain-text option if available (from prepare_explanation_options)
            option_display = distractor.get("option_plain", distractor["option"])
            html_parts.append(f'''
                <div style="color: #DC2626; font-weight: 500; margin-bottom: 0.5rem;">
                    <span style="margin-right: 0.5rem;">✗</span>
                    <span>Incorrect Option:</span>
                </div>
                <div style="margin-left: 1.75rem; margin-bottom: 0.5rem;">
                    {option_display}
                </div>
            ''')
            if distractor.get("explanation_why_it_is_incorrect"):
                html_parts.append(f'<div style="color: #6B7280; margin-left: 1.75rem; line-height: 1.5; font-size: 0.95rem;">{render_content(distractor["explanation_why_it_is_incorrect"])}</div>')
            html_parts.append('</div>')
        
        html_parts.append('</div>')
        html_parts.append('</div>')

    html_parts.append('</body></html>')
    return ''.join(html_parts)

def format_explanation_from_options_combined(options_combined: List[Dict], question_text: str = "") -> str:
    """
    Fallback method to build explanation from options_combined.
    Simplified: Just put all options in one highlighted box for MA, like SA.
    """
    html_parts = [f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        {get_explanation_css()}
    </style>
</head>
<body>
''']

    # Add question text at the top with enhanced card design matching the reference
    if question_text:
        html_parts.append(f'''
        <div style="
            background-color: #F8F9FA;
            padding: 16px 20px;
            margin-bottom: 20px;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        ">
            <div style="
                display: flex;
                align-items: flex-start;
                gap: 12px;
            ">
                <div style="
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    min-width: 20px;
                    min-height: 20px;
                    padding: 2px;
                    background: #EEF2FF;
                    border: 1px solid #818CF8;
                    border-radius: 4px;
                ">
                    <span style="font-size: 12px;">❓</span>
                </div>
                <div style="flex: 1;">
                    <h4 style="
                        margin: 0 0 8px 0;
                        color: #6B7280;
                        font-size: 11px;
                        font-weight: 600;
                        text-transform: uppercase;
                        letter-spacing: 0.08em;
                    ">Question:</h4>
                    <p style="
                        margin: 0;
                        color: #1F2937;
                        font-size: 14px;
                        line-height: 1.5;
                        font-weight: 400;
                    ">{question_text}</p>
                </div>
            </div>
        </div>
        ''')

    # Separate correct answers and distractors
    correct_items = [item for item in options_combined if item.get("answer_or_distractor") == "answer"]
    distractor_items = [item for item in options_combined if item.get("answer_or_distractor") == "distractor"]

    # Create question review box with correct answers and explanation
    html_parts.append('<div class="question-review-box">')
    
    if len(correct_items) == 1:
        # SA: Single answer
        html_parts.append('''
            <div class="correct-answer-label">
                <span>✓</span>
                <span>Correct Answer:</span>
            </div>
        ''')
        item = correct_items[0]
        # Strip VS Code mockup HTML from option - show simplified code in explanation
        option_display = strip_html_for_explanation(item["option"])
        html_parts.append(f'<div class="correct-answer-text">{option_display}</div>')
        
        # Add explanation within the box
        if item["explanation_why_it_is_correct_or_incorrect"]:
            html_parts.append('''
                <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #E5E7EB;">
                    <div class="explanation-label">
                        <span style="opacity: 0.7;">📝</span>
                        <span>Explanation:</span>
                    </div>
            ''')
            html_parts.append(f'<div class="explanation-text">{render_content(item["explanation_why_it_is_correct_or_incorrect"])}</div>')
            html_parts.append('</div>')
        
    elif len(correct_items) > 1:
        # MA: Multiple answers
        html_parts.append('''
            <div class="correct-answer-label">
                <span>✓</span>
                <span>Correct Answers:</span>
            </div>
        ''')
        
        # Add each correct answer with bullet points
        for item in correct_items:
            # Strip VS Code mockup HTML from option - show simplified code in explanation
            option_display = strip_html_for_explanation(item["option"])
            html_parts.append(f'<div class="correct-answer-text">• {option_display}</div>')
        
        # Add shared explanation within the box
        if correct_items and correct_items[0]["explanation_why_it_is_correct_or_incorrect"]:
            html_parts.append('''
                <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #E5E7EB;">
                    <div class="explanation-label">
                        <span style="opacity: 0.7;">📝</span>
                        <span>Explanation:</span>
                    </div>
            ''')
            html_parts.append(f'<div class="explanation-text">{render_content(correct_items[0]["explanation_why_it_is_correct_or_incorrect"])}</div>')
            html_parts.append('</div>')
    
    html_parts.append('</div>')  # Close question-review-box

    # Incorrect answers section with improved styling
    if distractor_items:
        html_parts.append('<div style="margin-top: 2rem; border-top: 1px solid #E5E7EB; padding-top: 1.5rem;">')
        html_parts.append('<h3 style="color: #DC2626; margin-bottom: 1rem;">Incorrect Options:</h3>')
        html_parts.append('<div class="option-explanations">')
        
        for item in distractor_items:
            html_parts.append('<div style="margin-bottom: 1.5rem;">')
            # Strip VS Code mockup HTML from option - show simplified code in explanation
            option_display = strip_html_for_explanation(item["option"])
            html_parts.append(f'''
                <div style="color: #DC2626; font-weight: 500; margin-bottom: 0.5rem;">
                    <span style="margin-right: 0.5rem;">✗</span>
                    <span>Incorrect Option:</span>
                </div>
                <div style="margin-left: 1.75rem; margin-bottom: 0.5rem;">
                    {option_display}
                </div>
            ''')
            if item["explanation_why_it_is_correct_or_incorrect"]:
                html_parts.append(f'<div style="color: #6B7280; margin-left: 1.75rem; line-height: 1.5; font-size: 0.95rem;">{render_content(item["explanation_why_it_is_correct_or_incorrect"])}</div>')
            html_parts.append('</div>')
        
        html_parts.append('</div>')
        html_parts.append('</div>')

    html_parts.append('</body></html>')
    return ''.join(html_parts)

def format_question(question_text: str, question_id: str = '') -> str:
    """Format the question with clean styling"""
    return f"""
    <html><body>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            margin: 0;
            padding: 16px;
            background-color: #f8f9fa;
        }}
        .question-container {{
            background-color: #ffffff;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 
                        0 1px 2px rgba(0, 0, 0, 0.06);
        }}
        .question-text {{
            color: #1f2937;
            font-size: 16px;
            line-height: 1.8;
            margin: 0;
            font-weight: 300;
        }}
        @media (max-width: 600px) {{
            .question-container {{
                padding: 16px;
                margin: 0 8px 12px 8px;
            }}
        }}
    </style>
    <div class="question-container">
        <div class="question-text">
            {question_text}
        </div>
    </div>
    </body></html>
    """

def format_options(options: List[str]) -> List[str]:
    """Format the options list"""
    option_html_template = """
    <div style="
        background-color: #ffffff;
        padding: 16px;
        line-height: 1.8;
        border-radius: 6px;
        border: 1px solid #E5E7EB;
        margin: 8px 0;
        font-weight: 300;
    ">
        {content}
    </div>
    """
    
    formatted_options = []
    for option in options:
        # Check if option already contains HTML tags
        if option.strip().startswith('<') and option.strip().endswith('>'):
            # Option already contains HTML, use it directly without wrapping in template
            # Add !important styles to body to prevent Thinkific from overriding VS Code mockup colors
            formatted_options.append(f'<html><body style="background: transparent !important; margin: 0 !important; padding: 0 !important;">{option}</body></html>')
        else:
            # Plain text option, format with newlines and apply template
            content = format_text_with_newlines(option)
            formatted_options.append(
                f"<html><body>{option_html_template.format(content=content)}</body></html>"
            )

    return formatted_options

def format_references(url_list: list) -> str:
    """Format references section with a list of URLs"""
    if not url_list or len(url_list) == 0:
        return ''

    # Generate list items for each URL
    list_items = []
    for url in url_list:
        if url:  # Only include non-empty URLs
            list_items.append(f'<li><a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a></li>')

    if not list_items:
        return ''

    return f'''
    <div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #e5e7eb;">
        <h4 style="color: #374151; margin-bottom: 10px; font-size: 14px; font-weight: 600;">References:</h4>
        <ul style="margin: 0; padding-left: 20px; font-size: 14px; line-height: 1.6;">
            {"".join(list_items)}
        </ul>
    </div>
    '''



class FormatQuizObjectWithHtmlInput(TypedDict, total=False):
    """Input schema for format_quiz_object_with_html function.

    This is STEP 3 in the Thinkific quiz generation pipeline.
    Receives combined data from combine_quiz_fields and applies HTML formatting.

    Input source: node_1_combine_quiz_fields output (16 fields)
    Output destination: node_3_improve_text_readability

    Input fields from combine_quiz_fields:
    - answer_indices, answer_letter, batch_name, concept_explanation,
    - correct_answers, distractors, explanation, key_concept_analogy,
    - key_concepts, memorable_takeaway, options, question, question_explanation,
    - question_type, summary_content, url_list

    Output fields (7 total - core quiz structure):
    - answer_indices, answer_letter, batch_name, explanation, options,
    - question, question_type
    """
    # -------------------------------------------------------------------------
    # Core quiz fields (will be HTML formatted)
    # -------------------------------------------------------------------------
    question: str                    # Quiz question text -> formatted HTML
    options: List[Any]               # Answer options -> formatted HTML list
    explanation: str                 # Combined explanation -> formatted HTML

    # -------------------------------------------------------------------------
    # Metadata fields (passthrough, no formatting)
    # -------------------------------------------------------------------------
    answer_letter: str               # e.g., 'A' or 'A,B,C' for MA
    answer_indices: List[int]        # Indices of correct answers [0, 2, 3]
    question_type: str               # 'SA' or 'MA'
    batch_name: str                  # Quiz batch identifier

    # -------------------------------------------------------------------------
    # Explanation data (used for HTML generation, not in output)
    # -------------------------------------------------------------------------
    correct_answers: List[dict]      # [{option, explanation_why_it_is_correct}, ...]
    distractors: List[dict]          # [{option, explanation_why_it_is_incorrect}, ...]

    # -------------------------------------------------------------------------
    # Feynman explanation fields (used for collapsible sections)
    # -------------------------------------------------------------------------
    question_explanation: str        # Detailed explanation of the question
    key_concept_analogy: str         # Analogy to help understand the concept
    memorable_takeaway: str          # Key point to remember
    key_concepts: List[Any]          # List of key concepts

    # -------------------------------------------------------------------------
    # Concept explanation (used for collapsible section)
    # -------------------------------------------------------------------------
    concept_explanation: str         # Primary educational content
    summary_content: str             # Legacy field for compatibility

    # -------------------------------------------------------------------------
    # References (used for links section)
    # -------------------------------------------------------------------------
    url_list: List[Any]              # List of reference URLs


@udf_tool()
def format_quiz_object_with_html(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply HTML formatting to pre-combined quiz fields.

    Input: Pre-processed data from combine_quiz_fields with:
        - question, options, explanation (core fields)
        - answer_letter, answer_indices, question_type, batch_name
        - correct_answers, distractors, memorable_takeaway, key_concepts, summary_content, url_list

    Output: Same structure with HTML formatting applied to question, options, explanation
    """
    # Handle content wrapper if present
    if 'content' in obj:
        content = obj['content']
    else:
        content = obj

    # Extract pre-processed fields (already validated/randomized by combine_quiz_fields)
    question_text = content.get('question', '')
    options = content.get('options', [])
    url_list = content.get('url_list', [])

    # Ensure url_list is always a list
    if not isinstance(url_list, list):
        url_list = [url_list] if url_list else []

    question_id = content.get('id', content.get('question_guid', content.get('guid', '')))

    # Apply HTML formatting
    formatted_question = format_question(question_text, question_id)
    formatted_options = format_options(options)

    # Check quiz type - for drop_down_self_assessment, don't include question in explanation
    quiz_type = content.get('quiz_type', '') or content.get('batch_name', '')
    if quiz_type == 'drop_down_self_assessment':
        # Temporarily clear question so explanation functions don't add it
        temp_question = content.get('question', '')
        content['question'] = ''
        base_explanation = format_explanation_ma_sa(content)
        content['question'] = temp_question  # Restore it
    else:
        base_explanation = format_explanation_ma_sa(content)
    
    # ============================================================================
    # EXPLANATION RENDERING - CUSTOMIZATION POINT
    # ============================================================================
    #
    # ⚠️ IMPORTANT: If you want to change how explanations are displayed to users,
    # this is where the final explanation HTML is assembled and rendered.
    #
    # The explanation structure is:
    # 1. Question text (top card)
    # 2. Correct answer(s) + explanation (green box) - from base_explanation
    # 3. Collapsible sections (optional educational content):
    #    - 🧠 Concept Analogy: Feynman-style explanation with analogies
    #    - 📖 Concept Explanation: Summary content + code snippets
    # 4. Incorrect Options (red boxes with explanations)
    # 5. References (source URLs)
    #
    # Data sources:
    # - base_explanation: Built from format_explanation_ma_sa() function (line 652)
    #   Contains correct answer(s) and their explanations
    # - question_explanation, key_concept_analogy, memorable_takeaway:
    #   Generated by the Feynman explanation agent in the workflow
    # - concept_explanation: Educational explanation of the underlying concept (new)
    # - code_snippets: Code examples extracted during summary generation
    # - distractors: Wrong answers with explanations why they're incorrect
    #
    # To modify the explanation layout, styles, or content:
    # 1. Adjust the collapsible_sections generation below
    # 2. Modify the CSS in get_explanation_css() function (line 447)
    # 3. Update format_explanation_ma_sa() for correct answer display (line 652)
    # ============================================================================

    # Generate collapsible explanation sections to insert before "Incorrect Options"
    collapsible_sections = ""

    # Create collapsible Concept Analogy section (from Feynman explanation agent)
    if 'question_explanation' in content and 'key_concept_analogy' in content and 'memorable_takeaway' in content:
        #question_exp = render_content(content['question_explanation'])
        #key_concept = render_content(content['key_concept_analogy'])
        memorable = render_content(content['memorable_takeaway'])
        #combined_feynman = f'{question_exp}\n\n{key_concept}\n\n{memorable}'
        combined_feynman = f'\n{memorable}'
        collapsible_sections += f'<details><summary>🧠 Memorable Takeaway</summary>{combined_feynman}</details>\n\n'

    # Create collapsible concept for key concepts (itemized list)
    if 'key_concepts' in content and content['key_concepts']:
        key_concepts_list = content['key_concepts']

        # Build an HTML list from key_concepts array
        if isinstance(key_concepts_list, list):
            items_html = ''.join([f'<li>{render_content(concept)}</li>' for concept in key_concepts_list])
            concept_content = f'<ul style="margin: 0.5rem 0; padding-left: 1.5rem; line-height: 1.8;">{items_html}</ul>'
        else:
            # Fallback if key_concepts is not a list (shouldn't happen, but just in case)
            concept_content = render_content(str(key_concepts_list))

        collapsible_sections += f'<details><summary>🔑 Key Concepts</summary>{concept_content}</details>\n\n'

    # Create collapsible concept explanation section (prefer 'concept_explanation', fall back to 'summary'/'summary_content')
    concept_text = content.get('concept_explanation') or content.get('summary') or content.get('summary_content')
    if concept_text:
        concept_content = render_content(concept_text)

        # Add code examples if they exist
        #if 'code_snippets' in content and content['code_snippets']:
        #    code_examples_html = render_code_snippets(content['code_snippets'])
        #    concept_content += f'\n\n<div style="margin-top: 1.5rem;">{code_examples_html}</div>'

        collapsible_sections += f'<details><summary>📖 Concept Explanation</summary>{concept_content}</details>\n\n'





    # Insert collapsible sections before "Incorrect Options:" if they exist
    if collapsible_sections and 'Incorrect Options:' in base_explanation:
        formatted_explanation = base_explanation.replace(
            '<h3 style="color: #DC2626; margin-bottom: 1rem;">Incorrect Options:</h3>',
            f'{collapsible_sections}<h3 style="color: #DC2626; margin-bottom: 1rem;">Incorrect Options:</h3>'
        )
    else:
        formatted_explanation = base_explanation

    # ============================================================================
    # END EXPLANATION RENDERING
    # ============================================================================

    # Add the references section
    formatted_explanation = f"{formatted_explanation} {format_references(url_list)}"

    formatted_obj = {
        "question": formatted_question,
        "options": formatted_options,
        "explanation": formatted_explanation,
        # Preserve metadata needed for asterisk function and other processing
        "answer_letter": content.get('answer_letter', ''),
        "answer_indices": content.get('answer_indices', []),
        "question_type": content.get('question_type', 'SA'),
        "batch_name": content.get('batch_name', ''),
    }

    return formatted_obj

def format_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wrapper function to format a single quiz object.
    This is the missing function referenced in format_dataset.
    """
    return format_quiz_object_with_html(obj)

def format_dataset(dataset: Union[Dict, List[Dict]]) -> List[Dict]:
    """
    Process a dataset and return formatted versions.
    Updated to work with the new field structure (no more thinkific naming).
    """
    if isinstance(dataset, dict):
        dataset = [dataset]
    
    return [format_object(obj) for obj in dataset]

def format_dataset_simple(dataset):
    """
    Simple version that processes a single item or list.
    Compatible with agent workflows.
    """
    if isinstance(dataset, list):
        return [format_object(obj) for obj in dataset]
    else:
        return [format_object(dataset)]