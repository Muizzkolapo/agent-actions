"""YAML syntax error formatter with code snippets."""

from typing import Dict, Any
import yaml

from .error_formatter_base import ErrorFormatter
from ..user_error import UserError


class YAMLSyntaxErrorFormatter(ErrorFormatter):
    """Handles YAML syntax errors with industry-standard formatting."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect YAML syntax errors."""
        # Check if it's a YAML error (from PyYAML library)
        if isinstance(root, yaml.YAMLError):
            return True

        # Check if it's a wrapped YAML error (ConfigurationError with YAML context)
        # This happens when render_workflow.py catches yaml.YAMLError and wraps it
        if hasattr(exc, 'context') and isinstance(exc.context, dict):
            ctx = exc.context
            # If context has line, column, and problem fields, it's likely a YAML error
            if 'problem' in ctx and 'line' in ctx and 'column' in ctx:
                return True
            # Check if operation suggests YAML parsing
            if ctx.get('operation') == 'parse_yaml':
                return True

        # Also check exception names for YAML-related errors
        exc_names = [type(exc).__name__, type(root).__name__]
        if any('YAML' in name for name in exc_names):
            return True

        return False

    def format(
        self,
        exc: Exception,
        root: Exception,
        message: str,
        context: Dict[str, Any]
    ) -> UserError:
        """Format YAML syntax errors with code snippet and visual indicators."""
        # Extract key info from context
        file_path = context.get('file_path') or context.get('config_file') or context.get('yaml_path')
        rendered_content = context.get('rendered_content')
        line = context.get('line')
        column = context.get('column')
        problem = context.get('problem', 'syntax error')

        # Get file name for title
        from pathlib import Path
        file_name = Path(file_path).name if file_path else 'configuration file'

        # Build title
        title = f"YAML syntax error in {file_name}"

        # Build details with just location and problem
        details_parts = []
        if line and column:
            details_parts.append(f"Line {line}, Column {column}: {problem}")
        else:
            details_parts.append(problem)

        # Add code snippet if available
        if rendered_content and line:
            snippet = self._get_code_snippet(rendered_content, line, column)
            if snippet:
                details_parts.append("\n" + snippet)

        # Get fix suggestion
        fix = self._get_fix_suggestion(problem)

        return UserError(
            category="YAML Syntax Error",
            title=title,
            details="\n".join(details_parts),
            fix=fix,
            context={'file_path': file_path} if file_path else None,
            docs_url="https://docs.agent-actions.com/troubleshooting/yaml-errors"
        )

    def _get_code_snippet(self, content: str, line_num: int, column_num: int) -> str:
        """Extract code snippet with visual indicator."""
        if not content or not line_num:
            return ""

        lines = content.split('\n')
        if line_num > len(lines):
            return ""

        # Show 2 lines before and 1 line after
        start_line = max(0, line_num - 3)
        end_line = min(len(lines), line_num + 2)

        snippet_lines = []
        for i in range(start_line, end_line):
            line_content = lines[i]
            display_line_num = i + 1

            if display_line_num == line_num:
                # Error line with indicator
                snippet_lines.append(f"> {display_line_num:3d} | {line_content}")
                # Add pointer
                if column_num:
                    pointer = " " * (column_num - 1) + "^^"
                    snippet_lines.append(f"      | {pointer}")
            else:
                # Context line
                snippet_lines.append(f"  {display_line_num:3d} | {line_content}")

        return "\n".join(snippet_lines)

    def _get_fix_suggestion(self, problem: str) -> str:
        """Get concise fix suggestion based on error."""
        if not problem:
            return "Check the YAML syntax and fix any errors."

        problem_lower = problem.lower()

        if "expected ':'" in problem_lower or "could not find expected ':'" in problem_lower:
            return "Missing ':' after key. Use 'key: value' syntax."

        if "mapping values are not allowed" in problem_lower:
            return "Check your indentation. Use spaces (not tabs), and ensure proper nesting."

        if "expected <block end>" in problem_lower:
            return "Check for unclosed lists or dictionaries. List items (-) must align."

        if "found unexpected end of stream" in problem_lower:
            return "File appears incomplete. Check for missing closing brackets or quotes."

        if "found character '\\t'" in problem_lower:
            return "Remove tab characters. Use spaces for indentation."

        if "could not find expected" in problem_lower and "key" in problem_lower:
            return "Invalid key format. Keys must be followed by a colon (:)."

        return "Check the YAML syntax at the indicated location."
