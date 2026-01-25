from typing import Any, Dict, List
from agent_actions import udf_tool
import html


def detect_language(code: str) -> str:
    """Detect programming language from code syntax - supports many languages."""
    if not code:
        return 'text'

    code_lower = code.lower()
    code_upper = code.upper()

    # dbt/Jinja templates (check FIRST before others)
    if '{%' in code or ('{{{' in code or '{{' in code and ('test' in code or 'model' in code_lower or 'endtest' in code)):
        return 'jinja'

    # YAML with macros/arguments (dbt schema files)
    if code.strip().startswith(('macros:', '- name: test_', 'arguments:')):
        return 'yaml'

    # Terraform/HCL
    if any(kw in code for kw in ['resource "', 'provider "', 'variable "', 'terraform {', 'module "']):
        return 'hcl'

    # Kubernetes/YAML manifests
    if any(marker in code for marker in ['apiVersion:', 'kind: ', 'metadata:', 'spec:']):
        return 'yaml'

    # Azure CLI / PowerShell
    if code.startswith(('az ', 'New-', 'Get-', 'Set-')) or 'Connect-AzAccount' in code:
        return 'powershell'

    # Docker
    if code.startswith(('FROM ', 'RUN ', 'COPY ', 'CMD ', 'ENTRYPOINT ')):
        return 'dockerfile'

    # Shell/Bash
    if code.startswith(('#!/bin/bash', '#!/bin/sh', 'export ', 'echo ')) or any(kw in code for kw in ['| grep', '| awk', '>> ']):
        return 'bash'

    # Python
    if any(kw in code for kw in ['def ', 'class ', 'import ', 'from ', '__init__', 'self.']):
        return 'python'

    # JavaScript/TypeScript
    if any(kw in code for kw in ['function ', 'const ', 'let ', 'var ', '=>', 'async ', 'await ']):
        return 'javascript'

    # Go
    if any(kw in code for kw in ['package ', 'func ', 'import (', 'type ', 'struct {']):
        return 'go'

    # Rust
    if any(kw in code for kw in ['fn ', 'let mut', 'impl ', 'pub ', 'use crate::']):
        return 'rust'

    # Java
    if any(kw in code for kw in ['public class', 'private ', 'protected ', 'import java.']):
        return 'java'

    # C#
    if any(kw in code for kw in ['using System', 'namespace ', 'public class', 'private ']):
        return 'csharp'

    # SQL
    if any(kw in code_upper for kw in ['SELECT ', 'FROM ', 'WHERE ', 'JOIN ', 'INSERT ', 'UPDATE ', 'CREATE TABLE']):
        return 'sql'

    # YAML (generic - check after specific YAML types)
    if code.strip().startswith(('- name:', 'name:', 'version:', 'description:', 'defaults:', 'actions:')):
        return 'yaml'

    # JSON
    if code.strip().startswith(('{', '[')) and any(marker in code for marker in ['": "', '": {', '": [', '":']):
        return 'json'

    # XML
    if code.strip().startswith('<') and '>' in code:
        return 'xml'

    return 'text'


def format_code_block(code: str, language: str = None) -> str:
    """
    Format code with proper HTML structure.

    Uses <pre><code> tags instead of <p> to preserve formatting.
    Does NOT escape HTML characters - code should be raw.
    """
    if not code:
        return ''

    # Auto-detect language if not provided
    if not language:
        language = detect_language(code)

    # Escape HTML entities for safe rendering
    # BUT don't escape Jinja/template syntax
    escaped_code = html.escape(code)

    # Wrap in proper code block structure
    # Using data-language attribute for potential syntax highlighting
    return f'<pre><code class="language-{language}">{escaped_code}</code></pre>'


def format_option_code(option: str) -> str:
    """
    Format a single option containing code.

    Detects if option is code and formats appropriately.
    Strips existing <p> tags if present.
    """
    if not option:
        return ''

    # Strip existing HTML paragraph tags if present
    # format_quiz_object may have already wrapped in <p> tags
    import re
    cleaned = re.sub(r'^<p>(.*)</p>$', r'\1', option.strip(), flags=re.DOTALL)

    # Check if this looks like code (multiple lines, code syntax, etc.)
    is_code = ('\n' in cleaned or
               any(marker in cleaned for marker in ['{%', '{{', 'def ', 'class ', '- name:',
                                                     'resource "', 'az ', 'SELECT', 'FROM']))

    if is_code:
        return format_code_block(cleaned)
    else:
        # Plain text option - re-wrap in <p>
        return f'<p>{cleaned}</p>'


@udf_tool()
def format_code_blocks(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Format code blocks in quiz options with proper HTML structure.

    Replaces <p> tags around code with <pre><code> for proper rendering.
    Preserves template syntax without double-escaping.

    Args:
        data: Quiz data with options containing code

    Returns:
        List with formatted code blocks
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    result = content.copy()

    # Format options list
    if 'options' in result and isinstance(result['options'], list):
        result['options'] = [
            format_option_code(opt) if isinstance(opt, str) else opt
            for opt in result['options']
        ]

    # Format options_combined
    if 'options_combined' in result and isinstance(result['options_combined'], list):
        for item in result['options_combined']:
            if isinstance(item, dict) and 'option' in item:
                item['option'] = format_option_code(item['option'])

    # Format correct_answers
    if 'correct_answers' in result and isinstance(result['correct_answers'], list):
        for answer in result['correct_answers']:
            if isinstance(answer, dict) and 'option' in answer:
                # Don't re-format if already formatted
                if not answer['option'].startswith('<pre>'):
                    answer['option'] = format_option_code(answer['option'])

    # Format distractors
    if 'distractors' in result and isinstance(result['distractors'], list):
        for distractor in result['distractors']:
            if isinstance(distractor, dict) and 'option' in distractor:
                # Don't re-format if already formatted
                if not distractor['option'].startswith('<pre>'):
                    distractor['option'] = format_option_code(distractor['option'])

    return [result]
