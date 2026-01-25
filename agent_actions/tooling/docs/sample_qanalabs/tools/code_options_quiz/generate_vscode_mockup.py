from typing import Any, Dict, List
from agent_actions import udf_tool
import re


def detect_language_and_filename(code: str) -> tuple:
    """Detect language and generate appropriate filename."""
    code_lower = code.lower()

    # dbt/Jinja templates
    if '{%' in code and 'test' in code:
        return 'jinja', 'custom_test.sql'

    # YAML with macros
    if code.strip().startswith(('macros:', '- name: test_')):
        return 'yaml', 'schema.yml'

    # Terraform
    if 'resource "' in code or 'provider "' in code:
        return 'hcl', 'main.tf'

    # Kubernetes
    if 'apiVersion:' in code or 'kind:' in code:
        return 'yaml', 'deployment.yaml'

    # Python
    if any(kw in code for kw in ['def ', 'class ', 'import ']):
        return 'python', 'script.py'

    # Docker
    if code.startswith(('FROM ', 'RUN ')):
        return 'dockerfile', 'Dockerfile'

    # Bash
    if code.startswith('#!/bin/bash') or any(kw in code for kw in ['| grep', 'export ']):
        return 'bash', 'script.sh'

    # SQL
    if any(kw in code.upper() for kw in ['SELECT ', 'FROM ', 'CREATE TABLE']):
        return 'sql', 'query.sql'

    # JavaScript
    if any(kw in code for kw in ['function ', 'const ', 'let ', '=>']):
        return 'javascript', 'script.js'

    # Default
    return 'text', 'code.txt'


def highlight_code(code: str, language: str) -> str:
    """Apply syntax highlighting based on language."""
    if not code:
        return ''

    # Escape HTML first
    code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    if language == 'python':
        # Strings (do FIRST to avoid matching quotes in HTML attributes)
        code = re.sub(r"('(?:[^'\\\\]|\\\\.)*'|\"(?:[^\"\\\\]|\\\\.)*\")", r"<span class='string'>\1</span>", code)
        # Comments
        code = re.sub(r'(#.*$)', r"<span class='comment'>\1</span>", code, flags=re.MULTILINE)
        # Keywords
        keywords = ['def', 'class', 'if', 'else', 'for', 'while', 'import', 'from', 'return', 'with', 'as']
        for kw in keywords:
            code = re.sub(rf'\b({kw})\b', r"<span class='keyword'>\1</span>", code)
        # Functions
        code = re.sub(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', r"<span class='function'>\1</span>(", code)

    elif language in ['yaml', 'hcl']:
        # Comments
        code = re.sub(r'(#.*$)', r"<span class='comment'>\1</span>", code, flags=re.MULTILINE)
        # Strings (do BEFORE keys to avoid matching quotes in HTML attributes)
        code = re.sub(r"('(?:[^'\\\\]|\\\\.)*'|\"(?:[^\"\\\\]|\\\\.)*\")", r"<span class='string'>\1</span>", code)
        # Keys (before colon) - use single quotes to avoid conflict
        code = re.sub(r'^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r"\1<span class='yaml-key'>\2</span>:", code, flags=re.MULTILINE)

    elif language == 'jinja':
        # Jinja tags
        code = re.sub(r'(\{%.*?%\})', r"<span class='keyword'>\1</span>", code)
        code = re.sub(r'(\{\{.*?\}\})', r"<span class='keyword'>\1</span>", code)
        # Comments
        code = re.sub(r'(--.*$)', r"<span class='comment'>\1</span>", code, flags=re.MULTILINE)
        # Keywords
        keywords = ['select', 'from', 'where', 'with', 'as', 'test', 'endtest']
        for kw in keywords:
            code = re.sub(rf'\b({kw})\b', r"<span class='sql-keyword'>\1</span>", code, flags=re.IGNORECASE)

    elif language == 'sql':
        # Comments
        code = re.sub(r'(--.*$)', r"<span class='comment'>\1</span>", code, flags=re.MULTILINE)
        # SQL Keywords
        keywords = ['SELECT', 'FROM', 'WHERE', 'JOIN', 'INSERT', 'UPDATE', 'CREATE', 'TABLE', 'WITH', 'AS']
        for kw in keywords:
            code = re.sub(rf'\b({kw})\b', r"<span class='sql-keyword'>\1</span>", code, flags=re.IGNORECASE)

    return code


def generate_vscode_mockup(code: str, language: str = None, filename: str = None) -> str:
    """Generate VS Code mockup HTML for code display."""
    if not code:
        return ''

    # Auto-detect language and filename if not provided
    if not language or not filename:
        detected_lang, detected_file = detect_language_and_filename(code)
        language = language or detected_lang
        filename = filename or detected_file

    # Apply syntax highlighting
    highlighted_code = highlight_code(code, language)

    # Language display names
    lang_names = {
        'python': 'Python',
        'javascript': 'JavaScript',
        'yaml': 'YAML',
        'jinja': 'Jinja/SQL',
        'hcl': 'Terraform',
        'sql': 'SQL',
        'bash': 'Bash',
        'dockerfile': 'Docker',
        'text': 'Text'
    }
    lang_display = lang_names.get(language, language.capitalize())

    # File extension icons (using FontAwesome classes as reference)
    icon_map = {
        'py': '🐍',
        'js': '📜',
        'yml': '📋',
        'yaml': '📋',
        'tf': '🔷',
        'sql': '🗄️',
        'sh': '💻',
        'txt': '📄'
    }
    ext = filename.split('.')[-1] if '.' in filename else 'txt'
    icon = icon_map.get(ext, '📄')

    html = f'''<div style="width: 100%; max-width: 900px; margin: 10px auto; background: #1e1e1e !important; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.3); font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
    <!-- Title Bar -->
    <div style="background: #323233 !important; padding: 8px 12px; display: flex; align-items: center; border-bottom: 1px solid #252526;">
        <div style="display: flex; gap: 6px; margin-right: auto;">
            <span style="width: 12px; height: 12px; border-radius: 50%; background: #ff5f56 !important;"></span>
            <span style="width: 12px; height: 12px; border-radius: 50%; background: #ffbd2e !important;"></span>
            <span style="width: 12px; height: 12px; border-radius: 50%; background: #27c93f !important;"></span>
        </div>
        <div style="color: #cccccc; font-size: 13px;">{filename} - {lang_display}</div>
        <div style="margin-left: auto;"></div>
    </div>

    <!-- Tab Bar -->
    <div style="background: #252526 !important; padding: 0; border-bottom: 1px solid #1e1e1e;">
        <div style="display: inline-block; background: #1e1e1e !important; color: #ffffff; padding: 10px 16px; font-size: 13px; border-right: 1px solid #252526; position: relative;">
            <span style="margin-right: 6px;">{icon}</span>{filename}
            <div style="position: absolute; bottom: 0; left: 0; right: 0; height: 2px; background: #007acc !important;"></div>
        </div>
    </div>

    <!-- Code Editor -->
    <div style="background: #1e1e1e !important; padding: 16px; overflow-x: auto;">
        <pre style="margin: 0; font-family: 'Consolas', 'Monaco', 'Courier New', monospace; font-size: 14px; line-height: 1.6; color: #d4d4d4 !important; background: #1e1e1e !important;"><code style="background: transparent !important; color: #d4d4d4 !important;">{highlighted_code}</code></pre>
    </div>

    <!-- Status Bar -->
    <div style="background: #007acc !important; color: #ffffff; padding: 5px 12px; font-size: 12px; display: flex; justify-content: space-between;">
        <div>
            <span style="margin-right: 12px;">⎇ main</span>
            <span>✓ 0 ⚠ 0</span>
        </div>
        <div>
            <span style="margin-left: 12px;">Ln 1, Col 1</span>
            <span style="margin-left: 12px;">{lang_display}</span>
        </div>
    </div>
</div>

<style>
    .keyword {{ color: #c586c0; font-weight: 500; }}
    .comment {{ color: #6a9955; font-style: italic; }}
    .string {{ color: #ce9178; }}
    .function {{ color: #dcdcaa; }}
    .yaml-key {{ color: #9cdcfe; }}
    .sql-keyword {{ color: #569cd6; font-weight: 500; }}
</style>'''

    return html


@udf_tool()
def generate_vscode_mockup_for_options(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Replace code options with VS Code mockup HTML.

    Takes quiz data and wraps all code options in VS Code-style HTML mockups
    for beautiful rendering in the LMS.
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    result = content.copy()

    # Format options list
    if 'options' in result and isinstance(result['options'], list):
        formatted_options = []
        for opt in result['options']:
            if isinstance(opt, str):
                # Strip existing HTML tags
                cleaned = re.sub(r'<[^>]+>', '', opt)
                # Generate VS Code mockup
                mockup = generate_vscode_mockup(cleaned)
                formatted_options.append(mockup)
            else:
                formatted_options.append(opt)
        result['options'] = formatted_options

    # Format options_combined
    if 'options_combined' in result and isinstance(result['options_combined'], list):
        for item in result['options_combined']:
            if isinstance(item, dict) and 'option' in item:
                # Strip existing HTML tags
                cleaned = re.sub(r'<[^>]+>', '', item['option'])
                # Generate VS Code mockup
                item['option'] = generate_vscode_mockup(cleaned)

    # Format correct_answers
    if 'correct_answers' in result and isinstance(result['correct_answers'], list):
        for answer in result['correct_answers']:
            if isinstance(answer, dict) and 'option' in answer:
                cleaned = re.sub(r'<[^>]+>', '', answer['option'])
                answer['option'] = generate_vscode_mockup(cleaned)

    # Format distractors
    if 'distractors' in result and isinstance(result['distractors'], list):
        for distractor in result['distractors']:
            if isinstance(distractor, dict) and 'option' in distractor:
                cleaned = re.sub(r'<[^>]+>', '', distractor['option'])
                distractor['option'] = generate_vscode_mockup(cleaned)

    return [result]
