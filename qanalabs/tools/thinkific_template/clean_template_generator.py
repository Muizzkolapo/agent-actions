import json
import random
import html
import re
import pandas as pd
import sys
from pathlib import Path

# Try to import Pygments for better syntax highlighting
try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.formatters import HtmlFormatter
    from pygments.util import ClassNotFound
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False

# VS Code Theme Definitions
VS_CODE_THEMES = {
    "dracula": {
        "name": "Dracula",
        "editor_bg": "#282a36",
        "title_bar_bg": "linear-gradient(to bottom, #44475a, #282a36)",
        "tab_bar_bg": "#1e1f29",
        "tab_bg": "#282a36",
        "status_bar_bg": "linear-gradient(to right, #bd93f9, #8be9fd)",
        "text_color": "#f8f8f2",
        "syntax": {
            "keyword": "#ff79c6",
            "comment": "#6272a4", 
            "string": "#f1fa8c",
            "function": "#50fa7b",
            "class_name": "#8be9fd",
            "number": "#bd93f9",
            "parameter": "#ffb86c",
            "property": "#50fa7b"
        },
        "blank_placeholder": {
            "bg": "linear-gradient(135deg, #44475a, #282a36)",
            "border": "#6272a4",
            "color": "#f8f8f2"
        }
    },
    "github_dark": {
        "name": "GitHub Dark",
        "editor_bg": "#0d1117",
        "title_bar_bg": "linear-gradient(to bottom, #21262d, #161b22)",
        "tab_bar_bg": "#1c2128",
        "tab_bg": "#161b22",
        "status_bar_bg": "linear-gradient(to right, #1f6feb, #0969da)",
        "text_color": "#e6edf3",
        "syntax": {
            "keyword": "#ff7b72",
            "comment": "#8b949e",
            "string": "#a5d6ff",
            "function": "#d2a8ff",
            "class_name": "#facc15",
            "number": "#79c0ff",
            "parameter": "#ffa657",
            "property": "#7ee787"
        },
        "blank_placeholder": {
            "bg": "linear-gradient(135deg, #21262d, #161b22)",
            "border": "#30363d",
            "color": "#e6edf3"
        }
    },
    "one_dark": {
        "name": "One Dark Pro",
        "editor_bg": "#282c34",
        "title_bar_bg": "linear-gradient(to bottom, #3c4048, #282c34)",
        "tab_bar_bg": "#21252b",
        "tab_bg": "#282c34",
        "status_bar_bg": "linear-gradient(to right, #61afef, #56b6c2)",
        "text_color": "#abb2bf",
        "syntax": {
            "keyword": "#c678dd",
            "comment": "#5c6370",
            "string": "#98c379",
            "function": "#61afef",
            "class_name": "#e5c07b",
            "number": "#d19a66",
            "parameter": "#e06c75",
            "property": "#56b6c2"
        },
        "blank_placeholder": {
            "bg": "linear-gradient(135deg, #3c4048, #282c34)",
            "border": "#5c6370",
            "color": "#abb2bf"
        }
    },
    "monokai": {
        "name": "Monokai",
        "editor_bg": "#272822",
        "title_bar_bg": "linear-gradient(to bottom, #383830, #272822)",
        "tab_bar_bg": "#1e1f1c",
        "tab_bg": "#272822",
        "status_bar_bg": "linear-gradient(to right, #a6e22e, #66d9ef)",
        "text_color": "#f8f8f2",
        "syntax": {
            "keyword": "#f92672",
            "comment": "#75715e",
            "string": "#e6db74",
            "function": "#a6e22e",
            "class_name": "#66d9ef",
            "number": "#ae81ff",
            "parameter": "#fd971f",
            "property": "#a6e22e"
        },
        "blank_placeholder": {
            "bg": "linear-gradient(135deg, #383830, #272822)",
            "border": "#75715e",
            "color": "#f8f8f2"
        }
    },
    "vscode_light": {
        "name": "VS Code Light",
        "editor_bg": "#ffffff",
        "title_bar_bg": "linear-gradient(to bottom, #f3f3f3, #ffffff)",
        "tab_bar_bg": "#f3f3f3",
        "tab_bg": "#ffffff",
        "status_bar_bg": "linear-gradient(to right, #007acc, #005a9e)",
        "text_color": "#000000",
        "syntax": {
            "keyword": "#0000ff",
            "comment": "#008000",
            "string": "#a31515",
            "function": "#795e26",
            "class_name": "#267f99",
            "number": "#098658",
            "parameter": "#001080",
            "property": "#0070c1"
        },
        "blank_placeholder": {
            "bg": "linear-gradient(135deg, #f3f3f3, #e8e8e8)",
            "border": "#cccccc",
            "color": "#000000"
        }
    }
}


def get_random_theme():
    """Select a random VS Code theme"""
    theme_key = random.choice(list(VS_CODE_THEMES.keys()))
    return theme_key, VS_CODE_THEMES[theme_key]

def generate_theme_css(theme_data):
    """Generate CSS based on the selected theme"""
    return f"""
        /* Theme: {theme_data['name']} */
        .vscode-container {{
            background-color: {theme_data['tab_bg']};
        }}
        
        .vscode-title-bar {{
            background: {theme_data['title_bar_bg']};
        }}
        
        .vscode-tab-bar {{
            background-color: {theme_data['tab_bar_bg']};
        }}
        
        .vscode-tab {{
            background-color: {theme_data['tab_bg']};
            color: {theme_data['text_color']};
        }}
        
        .vscode-editor {{
            background-color: {theme_data['editor_bg']};
            color: {theme_data['text_color']};
        }}
        
        .vscode-status-bar {{
            background: {theme_data['status_bar_bg']};
        }}
        
        /* Theme-specific syntax highlighting - Custom highlighter */
        .vscode-editor .keyword {{ color: {theme_data['syntax']['keyword']} !important; }}
        .vscode-editor .comment {{ color: {theme_data['syntax']['comment']} !important; }}
        .vscode-editor .string {{ color: {theme_data['syntax']['string']} !important; }}
        .vscode-editor .function {{ color: {theme_data['syntax']['function']} !important; }}
        .vscode-editor .class-name {{ color: {theme_data['syntax']['class_name']} !important; }}
        .vscode-editor .number {{ color: {theme_data['syntax']['number']} !important; }}
        .vscode-editor .parameter {{ color: {theme_data['syntax']['parameter']} !important; }}
        .vscode-editor .property {{ color: {theme_data['syntax']['property']} !important; }}
        
        /* Pygments-generated syntax highlighting */
        .vscode-editor .k {{ color: {theme_data['syntax']['keyword']} !important; }}
        .vscode-editor .c {{ color: {theme_data['syntax']['comment']} !important; font-style: italic !important; }}
        .vscode-editor .s, .vscode-editor .s1, .vscode-editor .s2 {{ color: {theme_data['syntax']['string']} !important; }}
        .vscode-editor .nf {{ color: {theme_data['syntax']['function']} !important; }}
        .vscode-editor .nc {{ color: {theme_data['syntax']['class_name']} !important; }}
        .vscode-editor .m, .vscode-editor .mi, .vscode-editor .mf {{ color: {theme_data['syntax']['number']} !important; }}
        .vscode-editor .n, .vscode-editor .nn, .vscode-editor .nt {{ color: {theme_data['syntax']['parameter']} !important; }}
        .vscode-editor .na {{ color: {theme_data['syntax']['property']} !important; }}
        .vscode-editor .p {{ color: {theme_data['text_color']} !important; }}
        .vscode-editor .o {{ color: {theme_data['text_color']} !important; }}
        
        /* Theme-specific blank placeholder */
        .blank-placeholder {{
            background: {theme_data['blank_placeholder']['bg']};
            border-color: {theme_data['blank_placeholder']['border']};
            color: {theme_data['blank_placeholder']['color']};
        }}
        
        .blank-placeholder::before {{
            background: linear-gradient(135deg, 
                rgba(88,166,255,0.1), 
                rgba(88,166,255,0.05)
            );
        }}
    """

def create_dynamic_quiz(data, output_filename="quiz.html"):
    """
    Creates a completely dynamic quiz from scratch using only the specific number of blanks in the data.
    
    Args:
        data (dict): Quiz data containing blanks, wrong answers, code, etc.
        output_filename (str): Name of the output HTML file
        
    Returns:
        str: Path to the generated HTML file
    """
    
    # Select random theme
    theme_key, selected_theme = get_random_theme()
    print(f"🎨 Selected theme: {selected_theme['name']}")
    
    # Extract data from JSON
    user_prompt = data.get("user_prompt", "Complete the code challenge.")
    code_explanation = data.get("CodeExplanation", "No explanation provided.")
    blanked_code = data.get("blanked_code", "")
    
    # Process blanks and wrong answers
    blanks_info = {}
    all_wrong_answers = {item['placeholder_id']: item['wrong_answers'] for item in data['wrong_answers']}
    
    for i, blank in enumerate(data['blanks']):
        placeholder = blank['placeholder_id']
        correct_answer = blank['original_text']
        
        # Combine correct and wrong answers and shuffle them
        options = all_wrong_answers.get(placeholder, []) + [correct_answer]
        random.shuffle(options)
        
        blanks_info[f"BLANK_{i+1}"] = {
            "placeholder": placeholder,
            "correct": correct_answer,
            "options": options,
            "title": blank.get("explanation") or f"Choose the correct option for blank {i+1}"
        }
    
    num_blanks = len(blanks_info)
    
    # Detect language and get language info
    detected_language = detect_code_language(blanked_code)
    language_info = get_language_info(detected_language)
    
    # Apply syntax highlighting to code
    highlighted_code = apply_syntax_highlighting_to_code(blanked_code, blanks_info, selected_theme)
    
    # Generate dynamic content sections
    answer_section_html = generate_answer_section_html(blanks_info)
    results_section_html = generate_results_section_html(blanks_info, code_explanation)
    dynamic_css = generate_dynamic_feedback_css(blanks_info)
    theme_css = generate_theme_css(selected_theme)
    
    # Generate the complete HTML template
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VS Code Quiz - {language_info['description']}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        body {{
            font-family: 'Inter', sans-serif;
            background-color: #0d1117;
            color: #e6edf3;
            margin: 0;
            padding: 20px;
            box-sizing: border-box;
            min-height: 100vh;
            background-image: radial-gradient(circle at 25% 25%, #1f2937 0%, transparent 50%), 
                             radial-gradient(circle at 75% 75%, #374151 0%, transparent 50%);
        }}
        
        .quiz-container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        
        .vscode-container {{
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5), 
                        0 0 0 1px rgba(255,255,255,0.06),
                        inset 0 1px 0 rgba(255,255,255,0.04);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            border: 1px solid #30363d;
            margin-bottom: 30px;
        }}
        
        .vscode-title-bar {{
            padding: 12px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid rgba(0,0,0,0.2);
        }}
        
        .controls {{ 
            display: flex; 
            gap: 8px; 
        }}
        
        .control-dot {{ 
            width: 12px; 
            height: 12px; 
            border-radius: 50%; 
            box-shadow: inset 0 1px 2px rgba(0,0,0,0.3);
        }}
        
        .dot-red {{ 
            background: linear-gradient(145deg, #ff6058, #e5534b);
            border: 0.5px solid #d73a49;
        }}
        .dot-yellow {{ 
            background: linear-gradient(145deg, #ffbd2e, #e6a800);
            border: 0.5px solid #fb8500;
        }}
        .dot-green {{ 
            background: linear-gradient(145deg, #28ca42, #22a835);
            border: 0.5px solid #28a745;
        }}
        
        .title-text {{ 
            font-size: 13px; 
            color: #f0f6fc; 
            font-weight: 500;
        }}

        .vscode-tab-bar {{
            padding: 0;
            display: flex;
            border-bottom: 1px solid rgba(0,0,0,0.2);
        }}
        
        .vscode-tab {{
            padding: 12px 18px;
            font-size: 13px;
            border-right: 1px solid rgba(0,0,0,0.2);
            position: relative;
            display: flex;
            align-items: center;
            font-weight: 500;
        }}
        
        .vscode-tab::after {{
            content: '';
            position: absolute;
            bottom: 0; 
            left: 0; 
            right: 0;
            height: 2px;
            background: linear-gradient(90deg, #58a6ff, #1f6feb);
        }}

        .vscode-editor-area {{
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            min-height: 250px; /* Adjusted height */
        }}

        .vscode-editor {{
            padding: 24px;
            font-family: 'Cascadia Code', 'SF Mono', 'Monaco', 'Consolas', 'Roboto Mono', 'Ubuntu Mono', monospace;
            font-size: 14px;
            font-weight: 400;
            line-height: 1.5;
            overflow: auto;
            flex-grow: 1;
            letter-spacing: 0.025em;
        }}
        
        .vscode-editor pre {{ 
            margin: 0; 
            white-space: pre-wrap; 
            word-wrap: break-word; 
        }}
        
        .vscode-editor code {{ 
            display: block; 
        }}

        /* Base Syntax Highlighting - will be overridden by theme */
        .vscode-editor .keyword {{ font-weight: 600; }}
        .vscode-editor .comment {{ font-style: italic; }}
        .vscode-editor .function {{ font-weight: 500; }}
        .vscode-editor .class-name {{ font-weight: 500; }}
        .vscode-editor .number {{ font-weight: 500; }}


        .blank-placeholder {{
            padding: 4px 10px;
            border-radius: 4px;
            border: 1.5px dashed;
            display: inline-block;
            min-width: 100px;
            text-align: center;
            font-style: normal;
            font-family: inherit;
            font-size: 13px;
            font-weight: 600;
            box-shadow: 0 1px 3px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.1);
            animation: pulse 3s infinite;
            position: relative;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ border-color: #30363d; }}
            50% {{ border-color: #58a6ff; }}
        }}

        .vscode-status-bar {{
            color: white;
            padding: 8px 16px;
            font-size: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 500;
        }}
        
        .status-item {{ 
            margin-right: 16px; 
            display: inline-flex; 
            align-items: center; 
        }}
        
        .status-item i {{ 
            margin-right: 6px; 
        }}
        
        .quiz-instructions {{
            background: linear-gradient(145deg, #1c2128 0%, #161b22 100%);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 16px 40px rgba(0,0,0,0.4), 
                        0 0 0 1px rgba(255,255,255,0.08);
            border: 1px solid #30363d;
            margin-bottom: 30px;
        }}
        
        .quiz-title {{
            color: #f0f6fc;
            margin-bottom: 16px;
            font-size: 20px;
            font-weight: 600;
            display: flex;
            align-items: center;
        }}
        
        .quiz-prompt {{
            color: #8b949e;
            margin-bottom: 24px;
            font-size: 15px;
            line-height: 1.5;
            background-color: rgba(13,17,23,0.4);
            padding: 16px;
            border-radius: 8px;
            border-left: 3px solid #58a6ff;
        }}
        
        .answer-section {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 30px;
            margin-top: 20px;
        }}
        
        .blank-info {{
            background: rgba(88,166,255,0.05);
            border: 1px solid rgba(88,166,255,0.2);
            border-radius: 8px;
            padding: 20px;
        }}
        
        .blank-title {{
            color: #58a6ff;
            font-weight: 600;
            margin-bottom: 12px;
            font-size: 16px;
            display: flex;
            align-items: center;
        }}
        
        .options-list {{
            list-style: none;
            padding: 0;
            margin: 12px 0;
        }}
        
        .option-item {{
            position: relative;
            margin-bottom: 8px;
        }}
        
        .option-input {{
            position: absolute;
            opacity: 0;
            cursor: pointer;
        }}
        
        .option-label {{
            background: linear-gradient(135deg, #21262d, #161b22);
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 12px 16px;
            font-family: 'SF Mono', 'Monaco', 'Cascadia Code', 'Roboto Mono', monospace;
            font-size: 14px;
            font-weight: 500;
            color: #e6edf3;
            transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
            display: block;
            user-select: none;
            position: relative;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }}
        
        .option-label:hover {{
            border-color: #58a6ff;
            background: linear-gradient(135deg, #2a2f36, #1e2328);
            box-shadow: 0 2px 8px rgba(0,0,0,0.25), 0 0 0 1px rgba(88,166,255,0.2);
            transform: translateY(-1px);
        }}
        
        .option-input:checked + .option-label {{
            border-color: #58a6ff;
            background: linear-gradient(135deg, #1e3a5f, #1a2f4a);
            color: #58a6ff;
            box-shadow: 0 0 0 2px rgba(88,166,255,0.3), 0 2px 8px rgba(88,166,255,0.1);
            transform: translateY(-1px);
        }}
        
        /* Hide results initially */
        .results {{
            display: none;
        }}
        
        .hint {{
            background: rgba(88,166,255,0.1);
            border: 1px solid rgba(88,166,255,0.3);
            color: #58a6ff;
            padding: 12px;
            border-radius: 6px;
            font-size: 13px;
            display: flex;
            align-items: flex-start;
            margin-top: 12px;
        }}
        
        .thinking-points {{
            background: linear-gradient(135deg, #1f2937, #1c2128);
            border: 1px solid #58a6ff;
            color: #58a6ff;
            padding: 20px;
            border-radius: 8px;
            margin-top: 30px;
        }}
        
        .thinking-points h3 {{
            color: #f0f6fc;
            margin-top: 0;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
        }}
        
        .thinking-points ul {{
            margin: 0;
            padding-left: 20px;
        }}
        
        .thinking-points li {{
            margin-bottom: 8px;
            line-height: 1.4;
        }}
        
        @media (max-width: 768px) {{
            .answer-section {{
                grid-template-columns: 1fr;
                gap: 20px;
            }}
        }}
        
        {theme_css}
        
        {dynamic_css}
    </style>
</head>
<body>
    <div class="quiz-container">
        <div class="vscode-container">
            <div class="vscode-title-bar">
                <div class="controls">
                    <span class="control-dot dot-red"></span>
                    <span class="control-dot dot-yellow"></span>
                    <span class="control-dot dot-green"></span>
                </div>
                <div class="title-text">code_challenge{language_info['file_extension']} - {language_info['description']}</div>
                <div></div>
            </div>

            <div class="vscode-tab-bar">
                <div class="vscode-tab">
                    <i class="{language_info['icon_class']}" style="margin-right: 8px; color: {language_info['icon_color']};"></i>
                    code_challenge{language_info['file_extension']}
                </div>
            </div>

            <div class="vscode-editor-area">
                <div class="vscode-editor">
                    <pre><code>{highlighted_code}</code></pre>
                </div>
            </div>

            <div class="vscode-status-bar">
                <div class="status-left">
                    <span class="status-item"><i class="fas fa-code-branch"></i>main</span>
                    <span class="status-item"><i class="fas fa-exclamation-triangle"></i>{num_blanks} Issues</span>
                </div>
                <div class="status-right">
                    <span class="status-item">Ln 1, Col 15</span>
                    <span class="status-item">{language_info['display_name']}</span>
                    <span class="status-item">UTF-8</span>
                    <span class="status-item"><i class="{language_info['icon_class']}"></i></span>
                </div>
            </div>
        </div>
        
        <div class="quiz-instructions">
            <div class="quiz-title">
                <i class="fas fa-puzzle-piece" style="margin-right: 12px; color: #58a6ff;"></i>
                Interactive Code Challenge
            </div>
            
            <div class="quiz-prompt">
                <strong>Your Task:</strong> {html.escape(user_prompt)}
            </div>
            
            <div class="answer-section">{answer_section_html}
            </div>
        </div>
        
        {results_section_html}
    </div>
</body>
</html>"""

    # Write the final HTML
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    return output_filename


def detect_code_language(code):
    """
    Detect programming language from code content.
    Returns language identifier for Pygments or fallback to 'python'.
    """
    if not code:
        return 'text'
    
    # Check for YAML indicators
    yaml_indicators = ['version:', 'config:', 'schema:', 'tables:', '- name:', 'description:']
    if any(indicator in code.lower() for indicator in yaml_indicators):
        return 'yaml'
    
    # Check for Python indicators
    python_indicators = ['def ', 'class ', 'import ', 'from ', 'if __name__']
    if any(indicator in code for indicator in python_indicators):
        return 'python'
    
    # Check for other common languages
    if any(indicator in code for indicator in ['function ', 'const ', 'let ', 'var ']):
        return 'javascript'
    
    if any(indicator in code for indicator in ['public class', 'private ', 'public static']):
        return 'java'
    
    # Default fallback
    return 'text'

def get_language_info(language):
    """
    Get display information for a detected language.
    Returns dict with display name, file extension, and icon info.
    """
    language_map = {
        'python': {
            'display_name': 'Python',
            'file_extension': '.py',
            'icon_class': 'fab fa-python',
            'icon_color': '#ffd43b',
            'description': 'Python Fill-in-the-Blanks'
        },
        'yaml': {
            'display_name': 'YAML',
            'file_extension': '.yml',
            'icon_class': 'fas fa-file-code',
            'icon_color': '#cc8899',
            'description': 'YAML Configuration'
        },
        'javascript': {
            'display_name': 'JavaScript',
            'file_extension': '.js',
            'icon_class': 'fab fa-js-square',
            'icon_color': '#f7df1e',
            'description': 'JavaScript Fill-in-the-Blanks'
        },
        'java': {
            'display_name': 'Java',
            'file_extension': '.java',
            'icon_class': 'fab fa-java',
            'icon_color': '#f89820',
            'description': 'Java Fill-in-the-Blanks'
        },
        'text': {
            'display_name': 'Text',
            'file_extension': '.txt',
            'icon_class': 'fas fa-file-alt',
            'icon_color': '#888',
            'description': 'Text Fill-in-the-Blanks'
        }
    }
    
    return language_map.get(language, language_map['text'])

def highlight_code_with_pygments(code, language='python', theme_data=None):
    """
    Highlight code using Pygments with VS Code theme colors.
    """
    if not PYGMENTS_AVAILABLE:
        return html.escape(code)
    
    try:
        # Get the lexer for the language
        lexer = get_lexer_by_name(language)
        
        # Create custom formatter with VS Code-like colors
        if theme_data:
            style_defs = {
                'Token.Keyword': f"color: {theme_data['syntax']['keyword']}",
                'Token.Comment': f"color: {theme_data['syntax']['comment']}; font-style: italic",
                'Token.String': f"color: {theme_data['syntax']['string']}",
                'Token.Name.Function': f"color: {theme_data['syntax']['function']}",
                'Token.Name.Class': f"color: {theme_data['syntax']['class_name']}",
                'Token.Number': f"color: {theme_data['syntax']['number']}",
                'Token.Name': f"color: {theme_data['syntax']['parameter']}",
                'Token.Name.Attribute': f"color: {theme_data['syntax']['property']}",
                'Token.Punctuation': f"color: {theme_data['text_color']}",
            }
            
            # Create a custom CSS style string
            css_style = ''
            for token_type, style in style_defs.items():
                css_class = token_type.replace('Token.', '').replace('.', '_').lower()
                css_style += f".{css_class} {{ {style}; }}\n"
        
        # Use HTML formatter without CSS classes, inline styles instead
        formatter = HtmlFormatter(nowrap=True, noclasses=True, style='github-dark')
        
        # Highlight the code
        highlighted = highlight(code, lexer, formatter)
        
        return highlighted
        
    except (ClassNotFound, Exception):
        # Fallback to basic highlighting if Pygments fails
        return html.escape(code)

def apply_syntax_highlighting_to_code(code, blanks_info, theme_data=None):
    """
    Prepares code by inserting temporary placeholders for blanks, then calls the appropriate highlighter.
    This function acts as a bridge between the quiz data and the highlighters.
    """
    if not code:
        return ''
    
    # First, we need to find all occurrences of each placeholder and replace them systematically
    temp_code = code
    placeholder_map = {}
    temp_counter = 1
    
    # Go through each blank and find ALL occurrences of its placeholder
    for blank_num, blank_data in blanks_info.items():
        placeholder = blank_data["placeholder"]
        
        # Find all occurrences of this placeholder
        while placeholder in temp_code:
            temp_marker = f'__TEMP_BLANK__{temp_counter}__'
            placeholder_map[temp_marker] = blank_num
            temp_code = temp_code.replace(placeholder, temp_marker, 1)
            temp_counter += 1

    # Detect language and choose appropriate highlighter
    language = detect_code_language(temp_code)
    
    if PYGMENTS_AVAILABLE and language != 'python':
        # Use Pygments for non-Python languages (like YAML)
        highlighted_code = highlight_code_with_pygments(temp_code, language, theme_data)
    else:
        # Use our custom Python highlighter for Python code
        highlighted_code = highlight_python_code(temp_code)
    
    # After highlighting, replace ALL temporary markers with the final styled HTML
    for temp_marker, blank_num in placeholder_map.items():
        highlighted_code = highlighted_code.replace(
            temp_marker,
            f'<span class="blank-placeholder">__{blank_num}__</span>'
        )
    
    return highlighted_code


def highlight_python_code(code):
    """
    Applies robust syntax highlighting to a Python code string.
    The strategy is to escape all HTML first, then apply highlighting rules.
    This prevents regexes from corrupting HTML tags.
    """
    if not code:
        return ''

    # 1. Escape the entire code block to handle '<', '>', '&' characters safely.
    code = html.escape(code)

    # 2. Define highlighting rules. Order is important: match longer, more specific patterns first.
    # Note: Regexes now match against escaped characters (e.g., &quot; for ").
    replacements = [
        # Strings (including multi-line docstrings)
        (r'(&quot;&quot;&quot;[\s\S]*?&quot;&quot;&quot;)', r'<span class="string">\1</span>'),
        (r"(&#x27;&#x27;&#x27;[\s\S]*?&#x27;&#x27;&#x27;)", r'<span class="string">\1</span>'),
        (r"(?<!&quot;)(&quot;(?!&quot;)(?:\\.|[^&])*?&quot;)(?!&quot;)", r'<span class="string">\1</span>'),
        (r"(?<!&#x27;)(&#x27;(?!&#x27;)(?:\\.|[^&])*?&#x27;)(?!&#x27;)", r'<span class="string">\1</span>'),
        
        # Comments
        (r'(#.*$)', r'<span class="comment">\1</span>'),
        
        # Keywords (including built-in constants)
        # Use negative lookbehind to avoid matching keywords inside HTML attributes
        (r'(?<![\w="])\\b(def|class|if|else|elif|for|while|try|except|finally|with|as|return|yield|import|from|pass|break|continue|in|is|not|and|or|lambda|async|await|True|False|None)\\b(?!=")', r'<span class="keyword">\1</span>'),
        
        # Function and class definition names
        # These patterns now look for already-highlighted keywords
        (r'<span class="keyword">def</span>\s+([a-zA-Z_]\w*)', r'<span class="keyword">def</span> <span class="function">\1</span>'),
        (r'<span class="keyword">class</span>\s+([a-zA-Z_]\w*)', r'<span class="keyword">class</span> <span class="class-name">\1</span>'),
        
        # Numbers (integers and floats)
        (r'\b(\d+\.?\d*)\b', r'<span class="number">\1</span>'),
        
        # Decorators
        (r'(@[a-zA-Z_]\w*)', r'<span class="function">\1</span>'),
    ]

    # 3. Apply all replacements sequentially
    for pattern, replacement in replacements:
        code = re.sub(pattern, replacement, code, flags=re.MULTILINE)

    return code


def generate_answer_section_html(blanks_info):
    """Generate the answer section HTML with dynamic blanks."""
    
    answer_blocks = ""
    
    for i, (blank_num, blank_data) in enumerate(blanks_info.items(), 1):
        options_html = ""
        
        for option in blank_data["options"]:
            option_id = f"b{i}_{''.join(filter(str.isalnum, option))}"
            options_html += f"""
                        <div class="option-item">
                            <input type="radio" name="blank{i}" value="{html.escape(option)}" class="option-input" id="{option_id}">
                            <label for="{option_id}" class="option-label">{html.escape(option)}</label>
                        </div>"""
        
        answer_blocks += f"""
                <div class="blank-info">
                    <div class="blank-title">
                        <span style="margin-right: 8px; background: #58a6ff; color: white; width: 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold;">{i}</span>
                        {blank_num}: {blank_data['title']}
                    </div>
                    <div class="options-list">{options_html}
                    </div>
                    <div class="hint">
                        <i class="fas fa-lightbulb" style="margin-right: 8px; margin-top: 2px; flex-shrink: 0;"></i>
                        <span>Choose the option that best fits the context.</span>
                    </div>
                </div>
                """
    
    return answer_blocks


def generate_results_section_html(blanks_info, code_explanation):
    """Generate the results section with correct answers."""
    
    correct_answers_html = ""
    for blank_num, blank_data in blanks_info.items():
        correct_answers_html += f'<li><strong>{blank_num}:</strong> "{blank_data["correct"]}"</li>'
    
    return f"""<div class="thinking-points results">
            <h3>
                <i class="fas fa-check-circle" style="margin-right: 10px; color: #56d364;"></i>
                Results & Explanation
            </h3>
            <ul>
                {correct_answers_html}
                <li><strong>Explanation:</strong> {html.escape(code_explanation)}</li>
            </ul>
        </div>"""


def generate_dynamic_feedback_css(blanks_info):
    """Generate CSS rules for showing results and correct/incorrect states ONLY when ALL blanks are filled."""
    
    num_blanks = len(blanks_info)
    
    # Create selector for when ALL blanks are checked - this is the key to waiting
    has_selectors = [f'input[name="blank{i}"]:checked' for i in range(1, num_blanks + 1)]
    all_checked_selector = f':has({"):has(".join(has_selectors)})'
    
    css = f"""
        /* Show results ONLY when all {num_blanks} blanks are selected */
        .quiz-container{all_checked_selector} .results {{
            display: block;
        }}
        """
    
    # Generate CSS for each blank's correct/incorrect states - ONLY when ALL are selected
    for i, (_, blank_data) in enumerate(blanks_info.items(), 1):
        correct_value = html.escape(blank_data["correct"])
        
        css += f"""
        /* Feedback for blank {i} - ONLY when ALL blanks are filled */
        .quiz-container{all_checked_selector} .option-input[name="blank{i}"][value="{correct_value}"]:checked + .option-label {{
            border-color: #238636;
            background: linear-gradient(135deg, #0d4429, #0f2419);
            color: #56d364;
            box-shadow: 0 0 0 1px rgba(35,134,54,0.4);
        }}
        
        .quiz-container{all_checked_selector} .option-input[name="blank{i}"][value="{correct_value}"]:checked + .option-label::after {{
            content: "✓ Correct";
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 11px;
            font-weight: 600;
            color: #56d364;
        }}
        
        .quiz-container{all_checked_selector} .option-input[name="blank{i}"]:not([value="{correct_value}"]):checked + .option-label {{
            border-color: #da3633;
            background: linear-gradient(135deg, #490202, #2d0d0d);
            color: #f85149;
        }}
        
        .quiz-container{all_checked_selector} .option-input[name="blank{i}"]:not([value="{correct_value}"]):checked + .option-label::after {{
            content: "✗ Incorrect";
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(--50%);
            font-size: 11px;
            font-weight: 600;
            color: #f85149;
        }}
        """
    
    return css


def process_datasets_file(json_file_path, output_csv_path="quiz_questions.csv"):
    """
    Process a JSON file containing an array of quiz datasets.
    Generate HTML for each object and export to CSV.
    
    Args:
        json_file_path (str): Path to the JSON file
        output_csv_path (str): Path for the output CSV file
        
    Returns:
        str: Path to the generated CSV file
    """
    
    # Load the JSON data
    with open(json_file_path, 'r', encoding='utf-8') as f:
        datasets = json.load(f)
    
    print(f"📁 Loading {len(datasets)} datasets from {json_file_path}")
    
    # Process each dataset
    results = []
    
    for i, dataset in enumerate(datasets, 1):
        print(f"🔄 Processing dataset {i}/{len(datasets)}")
        
        # Extract content from the dataset structure
        content = dataset.get('content', {})
        
        # Generate HTML for this dataset
        html_filename = f"quiz_{i}_{dataset.get('target_id', 'unknown')[:8]}.html"
        generated_html_path = create_dynamic_quiz(content, html_filename)
        
        # Read the generated HTML content
        with open(generated_html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Prepare row data for CSV in required format
        row_data = {
            'QuestionType': 'SA',
            'QuestionText': html_content,
            'Explanation': content.get('CodeExplanation', ''),
            'Choice1': 'No',
            'Choice2': '*Yes'
        }
        
        results.append(row_data)
        print(f"✅ Generated {html_filename}")
    
    # Create DataFrame and export to CSV
    df = pd.DataFrame(results)
    df.to_csv(output_csv_path, index=False, encoding='utf-8')
    
    print(f"📊 Exported {len(results)} quiz questions to {output_csv_path}")
    return output_csv_path


# Test with the provided JSON data
if __name__ == '__main__':
    # NOTE: The original blanked_code string used '\\n', which is a literal backslash followed by 'n'.
    # For a Python multiline string, you should use a single backslash '\n'. I have corrected this below.
    json_data = {
                "wrong_answers": [
                    {
                        "placeholder_id": "__BLANK_1__",
                        "wrong_answers": [
                            "edition",
                            "version_number",
                            "release",
                            "variant"
                        ]
                    },
                    {
                        "placeholder_id": "__BLANK_2__",
                        "wrong_answers": [
                            "data_sets",
                            "sources_list",
                            "input_sources",
                            "datasources"
                        ]
                    },
                    {
                        "placeholder_id": "__BLANK_3__",
                        "wrong_answers": [
                            "data_loader",
                            "importer",
                            "source_loader",
                            "puller"
                        ]
                    },
                    {
                        "placeholder_id": "__BLANK_4__",
                        "wrong_answers": [
                            "settings",
                            "options",
                            "parameters",
                            "attributes"
                        ]
                    },
                    {
                        "placeholder_id": "__BLANK_5__",
                        "wrong_answers": [
                            "after_warn",
                            "notify_after",
                            "alert_after",
                            "warn"
                        ]
                    },
                    {
                        "placeholder_id": "__BLANK_6__",
                        "wrong_answers": [
                            "modifications",
                            "adjustments",
                            "changes",
                            "substitutes"
                        ]
                    },
                    {
                        "placeholder_id": "__BLANK_7__",
                        "wrong_answers": [
                            "table_schema",
                            "database_schema",
                            "table_structure",
                            "table_definition"
                        ]
                    },
                    {
                        "placeholder_id": "__BLANK_8__",
                        "wrong_answers": [
                            "table_ref",
                            "table_id",
                            "reference",
                            "name_identifier"
                        ]
                    }
                ],
                "code_segment_id": "c56634cf-19c0-4401-a17b-ea9a40c94f29",
                "blanked_code": "__BLANK_1__: 2\n\n__BLANK_2__:\n  - name: <string> # required\n    description: <markdown_string>\n    database: <database_name>\n    schema: <schema_name>\n    __BLANK_3__: <string>\n\n    __BLANK_4__:\n      <source_config>: <config_value>\n      freshness:\n        loaded_at_field: <column_name>\n        warn_after:\n          count: <positive_integer>\n          period: minute | hour | day\n        __BLANK_5__:\n          count: <positive_integer>\n          period: minute | hour | day\n        filter: <where-condition>\n      meta: {{{{<dictionary>}}}\n      tags: [<string>]\n\n    __BLANK_6__: <string>\n\n    quoting:\n      database: true | false\n      __BLANK_7__: true | false\n      identifier: true | false\n\n    tables:\n      - name: <string> #required\n        description: <markdown_string>\n        __BLANK_8__: <table_name>\n        tests:\n          - <test>\n          - ... # declare additional tests\n        config:\n          loaded_at_field: <column_name>\n          meta: {{{{<dictionary>}}}\n          tags: [<string>]\n          freshness:\n            warn_after:\n              count: <positive_integer>\n              period: minute | hour | day\n            error_after:\n              count: <positive_integer>\n              period: minute | hour | day\n            filter: <where-condition>\n\n        quoting:\n          database: true | false\n          schema: true | false\n          identifier: true | false\n        external: {{{{<dictionary>}}}\n        columns:\n          - name: <column_name> # required\n            description: <markdown_string>\n            quote: true | false\n            tests:\n              - <test>\n              - ... # declare additional tests\n            config:\n              meta: {{{{<dictionary>}}}\n              tags: [<string>]\n          - name: ... # declare properties of additional columns\n\n      - name: ... # declare properties of additional source tables\n\n  - name: ... # declare properties of additional sources",
                "completed_code": "version: 2\n\nsources:\n  - name: <string> # required\n    description: <markdown_string>\n    database: <database_name>\n    schema: <schema_name>\n    loader: <string>\n\n    config:\n      <source_config>: <config_value>\n      freshness:\n        loaded_at_field: <column_name>\n        warn_after:\n          count: <positive_integer>\n          period: minute | hour | day\n        error_after:\n          count: <positive_integer>\n          period: minute | hour | day\n        filter: <where-condition>\n      meta: {{{{<dictionary>}}}\n      tags: [<string>]\n\n    overrides: <string>\n\n    quoting:\n      database: true | false\n      schema: true | false\n      identifier: true | false\n\n    tables:\n      - name: <string> #required\n        description: <markdown_string>\n        identifier: <table_name>\n        tests:\n          - <test>\n          - ... # declare additional tests\n        config:\n          loaded_at_field: <column_name>\n          meta: {{{{<dictionary>}}}\n          tags: [<string>]\n          freshness:\n            warn_after:\n              count: <positive_integer>\n              period: minute | hour | day\n            error_after:\n              count: <positive_integer>\n              period: minute | hour | day\n            filter: <where-condition>\n\n        quoting:\n          database: true | false\n          schema: true | false\n          identifier: true | false\n        external: {{{{<dictionary>}}}\n        columns:\n          - name: <column_name> # required\n            description: <markdown_string>\n            quote: true | false\n            tests:\n              - <test>\n              - ... # declare additional tests\n            config:\n              meta: {{{{<dictionary>}}}\n              tags: [<string>]\n          - name: ... # declare properties of additional columns\n\n      - name: ... # declare properties of additional source tables\n\n  - name: ... # declare properties of additional sources",
                "blanks": [
                    {
                        "placeholder_id": "__BLANK_1__",
                        "original_text": "version",
                        "explanation": ""
                    },
                    {
                        "placeholder_id": "__BLANK_2__",
                        "original_text": "sources",
                        "explanation": ""
                    },
                    {
                        "placeholder_id": "__BLANK_3__",
                        "original_text": "loader",
                        "explanation": ""
                    },
                    {
                        "placeholder_id": "__BLANK_4__",
                        "original_text": "config",
                        "explanation": ""
                    },
                    {
                        "placeholder_id": "__BLANK_5__",
                        "original_text": "error_after",
                        "explanation": ""
                    },
                    {
                        "placeholder_id": "__BLANK_6__",
                        "original_text": "overrides",
                        "explanation": ""
                    },
                    {
                        "placeholder_id": "__BLANK_7__",
                        "original_text": "schema",
                        "explanation": ""
                    },
                    {
                        "placeholder_id": "__BLANK_8__",
                        "original_text": "identifier",
                        "explanation": ""
                    }
                ],
                "answers": [
                    "version",
                    "sources",
                    "loader",
                    "config",
                    "error_after",
                    "overrides",
                    "schema",
                    "identifier"
                ],
                "user_prompt": "Complete the given configuration code by filling in each blank with the appropriate keys that define the structure of a data source setup. Focus on specifying the overall configuration version, the main data source list, loader-specific settings, and table attributes such as identifiers and schema-related options to ensure a complete and valid configuration.",
                "url": "",
                "id": "",
                "CodeExplanation": "The provided code sample defines a structured configuration schema for specifying data sources and their related tables within a data processing or transformation framework. It outlines the required attributes such as source names, descriptions, configurations, and properties for tables and columns, enabling the management of data freshness, metadata, and testing. Additionally, it facilitates the declaration of source-specific settings while supporting various configurations for efficient data handling.",
                "vscode_mockup": "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n    <meta charset=\"UTF-8\">\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n    <title>VS Code Mockup - untitled.txt</title>\n    <script src=\"https://cdn.tailwindcss.com\"></script>\n    <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap\" rel=\"stylesheet\">\n    <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css\">\n    <style>\n        body {\n            font-family: 'Inter', sans-serif;\n            background-color: #1a1d21;\n            color: #d4d4d4;\n            display: flex;\n            justify-content: center;\n            align-items: center;\n            min-height: 100vh;\n            padding: 20px;\n            box-sizing: border-box;\n        }\n        .vscode-container {\n            width: 100%;\n            max-width: 1000px;\n            background-color: #1f2428;\n            border-radius: 10px;\n            box-shadow: 0 15px 40px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.05);\n            overflow: hidden;\n            display: flex;\n            flex-direction: column;\n        }\n        .vscode-title-bar {\n            background-color: #32383e;\n            padding: 10px 15px;\n            display: flex;\n            align-items: center;\n            justify-content: space-between;\n            border-bottom: 1px solid #2a2f33;\n        }\n        .vscode-title-bar .controls { display: flex; gap: 8px; }\n        .vscode-title-bar .control-dot { width: 12px; height: 12px; border-radius: 50%; }\n        .vscode-title-bar .dot-red { background-color: #fc605c; }\n        .vscode-title-bar .dot-yellow { background-color: #fdbc40; }\n        .vscode-title-bar .dot-green { background-color: #34c749; }\n        .vscode-title-bar .title-text { font-size: 13px; color: #c5c8c6; }\n\n        .vscode-tab-bar {\n            background-color: #252a2e;\n            padding: 0;\n            display: flex;\n            border-bottom: 1px solid #1e2226;\n        }\n        .vscode-tab {\n            background-color: #1f2428;\n            color: #e0e0e0;\n            padding: 12px 18px;\n            font-size: 13px;\n            border-right: 1px solid #1e2226;\n            position: relative;\n            cursor: default;\n        }\n        .vscode-tab::after {\n            content: '';\n            position: absolute;\n            bottom: 0; left: 0; right: 0;\n            height: 2px;\n            background-color: #007fd4;\n        }\n\n        .vscode-editor-area {\n            flex-grow: 1;\n            display: flex;\n            flex-direction: column;\n            overflow: hidden;\n        }\n\n        .vscode-editor {\n            padding: 20px;\n            font-family: 'SF Mono', 'Consolas', 'Liberation Mono', Menlo, Courier, monospace;\n            font-size: 14px;\n            line-height: 1.7;\n            overflow: auto;\n            flex-grow: 1;\n            background-color: #1f2428;\n            color: #d4d4d4;\n        }\n        .vscode-editor pre { margin: 0; white-space: pre-wrap; word-wrap: break-word; }\n        .vscode-editor code { display: block; }\n\n        /* Syntax Highlighting */\n        .keyword { color: #c586c0; font-weight: 500; }\n        .comment { color: #7f848e; font-style: italic; }\n        .string { color: #d19a66; }\n        .function { color: #dcdcaa; }\n        .class-name { color: #4ec9b0; }\n        .parameter { color: #9cdcfe; }\n        .operator { color: #d4d4d4; }\n        .punctuation { color: #d4d4d4; }\n        .number { color: #b5cea8; }\n        .method { color: #dcdcaa; }\n        .property { color: #9cdcfe; }\n        .module { color: #4ec9b0; }\n        .yaml-key { color: #9cdcfe; }\n        .yaml-value { color: #ce9178; }\n\n        .blank-placeholder {\n            background-color: #2a2f33;\n            color: #a0a0a0;\n            padding: 3px 8px;\n            border-radius: 4px;\n            border: 1px dashed #4a4f53;\n            display: inline-block;\n            min-width: 110px;\n            text-align: center;\n            font-style: italic;\n            font-family: 'Inter', sans-serif;\n        }\n\n        .vscode-status-bar {\n            background-color: #007acc;\n            color: white;\n            padding: 6px 15px;\n            font-size: 12px;\n            display: flex;\n            justify-content: space-between;\n            align-items: center;\n        }\n        .vscode-status-bar .status-item { margin-right: 15px; display: inline-flex; align-items: center; }\n        .vscode-status-bar .status-item i { margin-right: 5px; }\n    </style>\n</head>\n<body>\n    <div class=\"vscode-container rounded-lg\">\n        <div class=\"vscode-title-bar\">\n            <div class=\"controls\">\n                <span class=\"control-dot dot-red\"></span>\n                <span class=\"control-dot dot-yellow\"></span>\n                <span class=\"control-dot dot-green\"></span>\n            </div>\n            <div class=\"title-text\">untitled.txt - Text (Fill in the blanks Quiz)</div>\n            <div></div>\n        </div>\n\n        <div class=\"vscode-tab-bar\">\n            <div class=\"vscode-tab\">\n                <i class=\"fas fa-file\" style=\"margin-right: 6px; color: #888;\"></i>untitled.txt\n            </div>\n        </div>\n\n        <div class=\"vscode-editor-area\">\n            <div class=\"vscode-editor\">\n                <pre><code><span class=\"blank-placeholder\">__BLANK_1__</span>: 2\n\n<span class=\"blank-placeholder\">__BLANK_3__</span>:\n  - name: &lt;string&gt; # required\n    description: &lt;markdown_string&gt;\n    database: &lt;database_name&gt;\n    schema: &lt;schema_name&gt;\n    <span class=\"blank-placeholder\">__BLANK_3__</span>: &lt;string&gt;\n\n    <span class=\"blank-placeholder\">__BLANK_4__</span>:\n      &lt;source_config&gt;: &lt;config_value&gt;\n      freshness:\n        loaded_at_field: &lt;column_name&gt;\n        warn_after:\n          count: &lt;positive_integer&gt;\n          period: minute | hour | day\n        <span class=\"blank-placeholder\">__BLANK_5__</span>:\n          count: &lt;positive_integer&gt;\n          period: minute | hour | day\n        filter: &lt;where-condition&gt;\n      meta: {{{{&lt;dictionary&gt;}}}\n      tags: [&lt;string&gt;]\n\n    <span class=\"blank-placeholder\">__BLANK_6__</span>: &lt;string&gt;\n\n    quoting:\n      database: true | false\n      <span class=\"blank-placeholder\">__BLANK_7__</span>: true | false\n      identifier: true | false\n\n    tables:\n      - name: &lt;string&gt; #required\n        description: &lt;markdown_string&gt;\n        <span class=\"blank-placeholder\">__BLANK_8__</span>: &lt;table_name&gt;\n        tests:\n          - &lt;test&gt;\n          - ... # declare additional tests\n        config:\n          loaded_at_field: &lt;column_name&gt;\n          meta: {{{{&lt;dictionary&gt;}}}\n          tags: [&lt;string&gt;]\n          freshness:\n            warn_after:\n              count: &lt;positive_integer&gt;\n              period: minute | hour | day\n            error_after:\n              count: &lt;positive_integer&gt;\n              period: minute | hour | day\n            filter: &lt;where-condition&gt;\n\n        quoting:\n          database: true | false\n          schema: true | false\n          identifier: true | false\n        external: {{{{&lt;dictionary&gt;}}}\n        columns:\n          - name: &lt;column_name&gt; # required\n            description: &lt;markdown_string&gt;\n            quote: true | false\n            tests:\n              - &lt;test&gt;\n              - ... # declare additional tests\n            config:\n              meta: {{{{&lt;dictionary&gt;}}}\n              tags: [&lt;string&gt;]\n          - name: ... # declare properties of additional columns\n\n      - name: ... # declare properties of additional source tables\n\n  - name: ... # declare properties of additional sources</code></pre>\n            </div>\n        </div>\n\n        <div class=\"vscode-status-bar\">\n            <div class=\"status-left\">\n                <span class=\"status-item\"><i class=\"fas fa-code-branch\"></i>main*</span>\n                <span class=\"status-item\"><i class=\"fas fa-exclamation-circle\"></i>0 <i class=\"fas fa-exclamation-triangle\"></i>0</span>\n            </div>\n            <div class=\"status-right\">\n                <span class=\"status-item\">Ln 1, Col 1</span>\n                <span class=\"status-item\">Spaces: 4</span>\n                <span class=\"status-item\">UTF-8</span>\n                <span class=\"status-item\">Text</span>\n                <span class=\"status-item\"><i class=\"fas fa-bell\"></i></span>\n            </div>\n        </div>\n    </div>\n</body>\n</html>",
                "completed": "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n    <meta charset=\"UTF-8\">\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n    <title>VS Code Mockup - untitled.txt</title>\n    <script src=\"https://cdn.tailwindcss.com\"></script>\n    <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap\" rel=\"stylesheet\">\n    <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css\">\n    <style>\n        body {\n            font-family: 'Inter', sans-serif;\n            background-color: #1a1d21;\n            color: #d4d4d4;\n            display: flex;\n            justify-content: center;\n            align-items: center;\n            min-height: 100vh;\n            padding: 20px;\n            box-sizing: border-box;\n        }\n        .vscode-container {\n            width: 100%;\n            max-width: 1000px;\n            background-color: #1f2428;\n            border-radius: 10px;\n            box-shadow: 0 15px 40px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.05);\n            overflow: hidden;\n            display: flex;\n            flex-direction: column;\n        }\n        .vscode-title-bar {\n            background-color: #32383e;\n            padding: 10px 15px;\n            display: flex;\n            align-items: center;\n            justify-content: space-between;\n            border-bottom: 1px solid #2a2f33;\n        }\n        .vscode-title-bar .controls { display: flex; gap: 8px; }\n        .vscode-title-bar .control-dot { width: 12px; height: 12px; border-radius: 50%; }\n        .vscode-title-bar .dot-red { background-color: #fc605c; }\n        .vscode-title-bar .dot-yellow { background-color: #fdbc40; }\n        .vscode-title-bar .dot-green { background-color: #34c749; }\n        .vscode-title-bar .title-text { font-size: 13px; color: #c5c8c6; }\n\n        .vscode-tab-bar {\n            background-color: #252a2e;\n            padding: 0;\n            display: flex;\n            border-bottom: 1px solid #1e2226;\n        }\n        .vscode-tab {\n            background-color: #1f2428;\n            color: #e0e0e0;\n            padding: 12px 18px;\n            font-size: 13px;\n            border-right: 1px solid #1e2226;\n            position: relative;\n            cursor: default;\n        }\n        .vscode-tab::after {\n            content: '';\n            position: absolute;\n            bottom: 0; left: 0; right: 0;\n            height: 2px;\n            background-color: #007fd4;\n        }\n\n        .vscode-editor-area {\n            flex-grow: 1;\n            display: flex;\n            flex-direction: column;\n            overflow: hidden;\n        }\n\n        .vscode-editor {\n            padding: 20px;\n            font-family: 'SF Mono', 'Consolas', 'Liberation Mono', Menlo, Courier, monospace;\n            font-size: 14px;\n            line-height: 1.7;\n            overflow: auto;\n            flex-grow: 1;\n            background-color: #1f2428;\n            color: #d4d4d4;\n        }\n        .vscode-editor pre { margin: 0; white-space: pre-wrap; word-wrap: break-word; }\n        .vscode-editor code { display: block; }\n\n        /* Syntax Highlighting */\n        .keyword { color: #c586c0; font-weight: 500; }\n        .comment { color: #7f848e; font-style: italic; }\n        .string { color: #d19a66; }\n        .function { color: #dcdcaa; }\n        .class-name { color: #4ec9b0; }\n        .parameter { color: #9cdcfe; }\n        .operator { color: #d4d4d4; }\n        .punctuation { color: #d4d4d4; }\n        .number { color: #b5cea8; }\n        .method { color: #dcdcaa; }\n        .property { color: #9cdcfe; }\n        .module { color: #4ec9b0; }\n        .yaml-key { color: #9cdcfe; }\n        .yaml-value { color: #ce9178; }\n\n        .blank-placeholder {\n            background-color: #2a2f33;\n            color: #a0a0a0;\n            padding: 3px 8px;\n            border-radius: 4px;\n            border: 1px dashed #4a4f53;\n            display: inline-block;\n            min-width: 110px;\n            text-align: center;\n            font-style: italic;\n            font-family: 'Inter', sans-serif;\n        }\n\n        .vscode-status-bar {\n            background-color: #007acc;\n            color: white;\n            padding: 6px 15px;\n            font-size: 12px;\n            display: flex;\n            justify-content: space-between;\n            align-items: center;\n        }\n        .vscode-status-bar .status-item { margin-right: 15px; display: inline-flex; align-items: center; }\n        .vscode-status-bar .status-item i { margin-right: 5px; }\n    </style>\n</head>\n<body>\n    <div class=\"vscode-container rounded-lg\">\n        <div class=\"vscode-title-bar\">\n            <div class=\"controls\">\n                <span class=\"control-dot dot-red\"></span>\n                <span class=\"control-dot dot-yellow\"></span>\n                <span class=\"control-dot dot-green\"></span>\n            </div>\n            <div class=\"title-text\">untitled.txt - Text (Completed)</div>\n            <div></div>\n        </div>\n\n        <div class=\"vscode-tab-bar\">\n            <div class=\"vscode-tab\">\n                <i class=\"fas fa-file\" style=\"margin-right: 6px; color: #888;\"></i>untitled.txt\n            </div>\n        </div>\n\n        <div class=\"vscode-editor-area\">\n            <div class=\"vscode-editor\">\n                <pre><code>version: 2\n\nloader:\n  - name: &lt;string&gt; # required\n    description: &lt;markdown_string&gt;\n    database: &lt;database_name&gt;\n    schema: &lt;schema_name&gt;\n    loader: &lt;string&gt;\n\n    config:\n      &lt;source_config&gt;: &lt;config_value&gt;\n      freshness:\n        loaded_at_field: &lt;column_name&gt;\n        warn_after:\n          count: &lt;positive_integer&gt;\n          period: minute | hour | day\n        error_after:\n          count: &lt;positive_integer&gt;\n          period: minute | hour | day\n        filter: &lt;where-condition&gt;\n      meta: {{{{&lt;dictionary&gt;}}}\n      tags: [&lt;string&gt;]\n\n    overrides: &lt;string&gt;\n\n    quoting:\n      database: true | false\n      schema: true | false\n      identifier: true | false\n\n    tables:\n      - name: &lt;string&gt; #required\n        description: &lt;markdown_string&gt;\n        identifier: &lt;table_name&gt;\n        tests:\n          - &lt;test&gt;\n          - ... # declare additional tests\n        config:\n          loaded_at_field: &lt;column_name&gt;\n          meta: {{{{&lt;dictionary&gt;}}}\n          tags: [&lt;string&gt;]\n          freshness:\n            warn_after:\n              count: &lt;positive_integer&gt;\n              period: minute | hour | day\n            error_after:\n              count: &lt;positive_integer&gt;\n              period: minute | hour | day\n            filter: &lt;where-condition&gt;\n\n        quoting:\n          database: true | false\n          schema: true | false\n          identifier: true | false\n        external: {{{{&lt;dictionary&gt;}}}\n        columns:\n          - name: &lt;column_name&gt; # required\n            description: &lt;markdown_string&gt;\n            quote: true | false\n            tests:\n              - &lt;test&gt;\n              - ... # declare additional tests\n            config:\n              meta: {{{{&lt;dictionary&gt;}}}\n              tags: [&lt;string&gt;]\n          - name: ... # declare properties of additional columns\n\n      - name: ... # declare properties of additional source tables\n\n  - name: ... # declare properties of additional sources</code></pre>\n            </div>\n        </div>\n\n        <div class=\"vscode-status-bar\">\n            <div class=\"status-left\">\n                <span class=\"status-item\"><i class=\"fas fa-code-branch\"></i>main*</span>\n                <span class=\"status-item\"><i class=\"fas fa-exclamation-circle\"></i>0 <i class=\"fas fa-exclamation-triangle\"></i>0</span>\n            </div>\n            <div class=\"status-right\">\n                <span class=\"status-item\">Ln 1, Col 1</span>\n                <span class=\"status-item\">Spaces: 4</span>\n                <span class=\"status-item\">UTF-8</span>\n                <span class=\"status-item\">Text</span>\n                <span class=\"status-item\"><i class=\"fas fa-bell\"></i></span>\n            </div>\n        </div>\n    </div>\n</body>\n</html>"
            }

    # Test with sample data (original functionality)
    if len(sys.argv) == 1:
        # Generate the quiz with sample data
        file_path = create_dynamic_quiz(json_data, "fixed_dynamic_quiz.html")
        print(f"✅ Successfully generated fixed dynamic quiz at: {file_path}")
    
    # Test with datasets file if provided
    if len(sys.argv) > 1:
        datasets_file = sys.argv[1]
        csv_output = sys.argv[2] if len(sys.argv) > 2 else "quiz_questions.csv"
        
        if Path(datasets_file).exists():
            csv_path = process_datasets_file(datasets_file, csv_output)
            print(f"🎯 Process completed! CSV file: {csv_path}")
        else:
            print(f"❌ File not found: {datasets_file}")
            print("Usage: python clean_template_generator.py [datasets.json] [output.csv]")