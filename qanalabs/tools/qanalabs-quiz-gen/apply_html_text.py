import json
import re
import os
import markdown2
import markdown
from html import escape
from typing import Dict, List, Any, Union

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

def render_markdown(text):
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
    Parse combined_explanation markdown and apply proper .option styling to option texts.
    Simplified approach: just wrap option paragraphs in styled divs without trying to split them.
    """
    if not combined_text:
        return ""
    
    # Convert markdown to HTML
    html_content = render_markdown(combined_text)
    
    # For any paragraph containing Option patterns (SA or MA), wrap the entire paragraph
    # This handles both "Option:" for SA and "Option 1: ... Option 2: ..." for MA
    html_content = re.sub(
        r'<p>(.*?(?:Option(?:\s+\d+)?:.*?))</p>',
        r'<div class="option">\1</div>',
        html_content,
        flags=re.DOTALL
    )
    
    # Pattern for distractor sections - wrap the option text after headings
    html_content = re.sub(
        r'(<h3[^>]*>Distractor \d+:</h3>)\s*<p>([^<]+)</p>',
        r'\1<div class="option">\2</div>',
        html_content
    )
    
    # Additional pattern for option-like content that starts with action verbs
    html_content = re.sub(
        r'<p>((?:Use a prebuilt|Register|Implement|Integrate|Train|Allow|Use|Store|Apply|Fine-tune|Expand|Develop)[^<]*)</p>',
        r'<div class="option">\1</div>',
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
        }

        /* Make sure all elements don't overflow */
        *, *::before, *::after {
            box-sizing: border-box;
            max-width: 100%;
        }

        body {
            font-family: 'Nunito', 'Segoe UI', Roboto, sans-serif;
            font-size: 15px;
            line-height: 1.8;
            color: #374151;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            font-weight: 300;
        }

        h1 {
            color: #0078D4;
            border-bottom: 2px solid #0078D4;
            padding-bottom: 10px;
            margin-top: 30px;
        }

        h2 {
            margin-top: 24px;
            color: #0078D4;
        }

        h3 {
            margin-top: 24px;
            margin-bottom: 16px;
        }

        .correct {
            color: #107C10;
        }

        .incorrect {
            color: #D83B01;
        }

        .option {
            margin-bottom: 20px;
            padding: 15px;
            border-radius: 5px;
            background-color: #F9F9F9;
            border-left: 5px solid #0078D4;
        }

        .explanation {
            margin-bottom: 20px;
        }

        /* Inline code (not inside pre) */
        :not(pre) > code {
            background-color: #F9FAFB;
            color: #374151;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: Menlo, Consolas, monospace;
            font-size: 90%;
            word-break: break-word;
        }

        /* Block code */
        pre {
            font-family: Menlo, Consolas, monospace;
            background-color: #1E1E1E;
            color: #F8F8F2;
            padding: 12px;
            border-radius: 6px;
            white-space: pre;
            overflow-x: auto;
            display: block;
            margin-bottom: 20px;
        }

        /* Ensure nested code in pre doesn't override styles */
        pre code {
            background: none;
            color: inherit;
            padding: 0;
            font-size: 100%;
        }

        .steps {
            background-color: #F0F7FF;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }

        .steps ol {
            margin-bottom: 0;
        }
    '''

def format_explanation_ma_sa(obj: Dict[str, Any]) -> str:
    """
    Generate explanation HTML that works for both MA and SA questions.
    Uses the new combined_explanation field if available, otherwise builds from options_combined.
    Now properly applies rich styling (overlay vibe) to combined_explanation content.
    """
    
    # Method 1: Use combined_explanation if available (preferred)
    if 'combined_explanation' in obj and obj['combined_explanation']:
        combined_text = obj['combined_explanation']
        
        # Parse the combined explanation to apply proper styling
        styled_html = parse_and_style_combined_explanation(combined_text)
        
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
    {styled_html}
</body>
</html>'''
    
    # Method 2: Build from options_combined (fallback) with rich styling
    return format_explanation_from_options_combined(obj.get('options_combined', []))

def format_explanation_from_options_combined(options_combined: List[Dict]) -> str:
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

    # Separate correct answers and distractors
    correct_items = [item for item in options_combined if item.get("answer_or_distractor") == "answer"]
    distractor_items = [item for item in options_combined if item.get("answer_or_distractor") == "distractor"]

    # Correct answer(s) section - simplified approach
    if len(correct_items) == 1:
        # SA: Single answer in one box
        html_parts.append('<h2 class="correct">Correct Answer:</h2>')
        item = correct_items[0]
        html_parts.append(f'<div class="option"><strong>Option:</strong> {escape(item["option"])}</div>')
        html_parts.append(f'<div class="explanation">{render_markdown(item["explanation_why_it_is_correct_or_incorrect"])}</div>')
    elif len(correct_items) > 1:
        # MA: All options in one box, just like how they appear in the screenshot
        html_parts.append('<h2 class="correct">Correct Answers:</h2>')
        
        # Build the combined options text
        options_text = ' '.join([
            f'<strong>Option {i}:</strong> {escape(item["option"])}'
            for i, item in enumerate(correct_items, 1)
        ])
        
        # Put all options in a single highlighted box
        html_parts.append(f'<div class="option">{options_text}</div>')
        
        # Add shared explanation after the options box
        if correct_items and correct_items[0]["explanation_why_it_is_correct_or_incorrect"]:
            html_parts.append(f'<div class="explanation">{render_markdown(correct_items[0]["explanation_why_it_is_correct_or_incorrect"])}</div>')

    # Incorrect answers section
    if distractor_items:
        html_parts.append('<h2>Incorrect Options:</h2>')
        for idx, item in enumerate(distractor_items, 1):
            html_parts.append(f'<h3 class="incorrect">Distractor {idx}:</h3>')
            html_parts.append(f'<div class="option">{escape(item["option"])}</div>')
            html_parts.append(f'<div class="explanation">{render_markdown(item["explanation_why_it_is_correct_or_incorrect"])}</div>')

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
    return [
        f"<html><body>{option_html_template.format(content=format_text_with_newlines(option))}</body></html>"
        for option in options
    ]

def format_link(url: str) -> str:
    """Format the learn more link"""
    if not url:
        return ''
    return f'''
    <div style="
        padding: 32px 24px;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        display: flex;
        justify-content: center;
    ">
        <a href="{url}"        
            target="_blank" 
            rel="noopener noreferrer" 
            style="
            position: relative;
            display: inline-flex;
            align-items: center;
            gap: 12px;
            padding: 12px 24px;
            background: linear-gradient(135deg, rgb(34, 197, 94) 0%, rgb(22, 163, 74) 50%, rgb(21, 128, 61) 100%);
            color: #ffffff;
            text-decoration: none;
            border-radius: 16px;
            font-size: 14px;
            font-weight: 600;
            letter-spacing: -0.025em;
            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 
                0 6px 24px rgba(34, 197, 94, 0.2),
                0 2px 8px rgba(0, 0, 0, 0.12),
                inset 0 1px 0 rgba(255, 255, 255, 0.2);
            cursor: pointer;
            overflow: hidden;
            backdrop-filter: blur(8px);
            "
            onmouseover="
                this.style.transform='translateY(-4px) scale(1.02)';
                this.style.boxShadow='0 12px 36px rgba(34, 197, 94, 0.28), 0 8px 16px rgba(0, 0, 0, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.3)';
                this.style.background='linear-gradient(135deg, rgb(22, 163, 74) 0%, rgb(21, 128, 61) 50%, rgb(20, 83, 45) 100%)';
                this.querySelector('.arrow').style.transform='translateX(4px)';
                this.querySelector('.shimmer').style.transform='translateX(200px)';
            "
            onmouseout="
                this.style.transform='translateY(0px) scale(1)';
                this.style.boxShadow='0 6px 24px rgba(34, 197, 94, 0.2), 0 2px 8px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.2)';
                this.style.background='linear-gradient(135deg, rgb(34, 197, 94) 0%, rgb(22, 163, 74) 50%, rgb(21, 128, 61) 100%)';
                this.querySelector('.arrow').style.transform='translateX(0px)';
                this.querySelector('.shimmer').style.transform='translateX(-200px)';
            "
            onmousedown="this.style.transform='translateY(-2px) scale(0.98)'"
            onmouseup="this.style.transform='translateY(-4px) scale(1.02)'"
            >
            <!-- Shimmer effect -->
            <div class="shimmer" style="
                position: absolute;
                top: 0;
                left: -100px;
                width: 100px;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
                transform: translateX(-200px);
                transition: transform 0.6s ease-out;
            "></div>
            
            <span style="position: relative; z-index: 1;">Learn more</span>
            
            <!-- Enhanced arrow with smooth animation -->
            <svg class="arrow" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="
                position: relative;
                z-index: 1;
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            ">
                <path d="M7 17L17 7"></path>
                <path d="M7 7h10v10"></path>
            </svg>
        </a>
    </div>
    '''

def format_quiz_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main formatting function that works with the new MA/SA data structure.
    """
    # Validate and clean the data first
    obj = validate_and_clean_answers(obj)
    
    # Extract field values with fallbacks for different naming conventions
    question_text = obj.get('question', '')
    options = obj.get('options', [])
    url = obj.get('url', obj.get('link', ''))
    question_id = obj.get('id', obj.get('question_guid', obj.get('guid', '')))
    
    # Build the formatted object - preserve answer_letter and answer_indices
    formatted_obj = {
        "question": format_question(question_text, question_id),
        "options": format_options(options),
        "answer_letter": obj.get('answer_letter', ''),  # Keep for asterisk function
        "answer_indices": obj.get('answer_indices', []),  # Keep for asterisk function
        "question_type": obj.get('question_type', 'SA'),  # Keep for asterisk function
        "explanation": f"<html><body>{format_explanation_ma_sa(obj)}</body></html> <html><body>{format_link(url)}</body></html>"
    }
    
    return formatted_obj

def format_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wrapper function to format a single quiz object.
    This is the missing function referenced in format_dataset.
    """
    return format_quiz_object(obj)

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