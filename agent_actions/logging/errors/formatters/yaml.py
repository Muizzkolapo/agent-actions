"""YAML syntax error formatter with code snippets."""

from pathlib import Path
from typing import Any

import yaml

from ..user_error import UserError
from .base import ErrorFormatter


class YAMLSyntaxErrorFormatter(ErrorFormatter):
    """Handles YAML syntax errors with industry-standard formatting."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        if isinstance(root, yaml.YAMLError):
            return True

        if hasattr(exc, "context") and isinstance(exc.context, dict):
            ctx = exc.context
            if "problem" in ctx and "line" in ctx and "column" in ctx:
                return True
            if ctx.get("operation") == "parse_yaml":
                return True

        exc_names = [type(exc).__name__, type(root).__name__]
        if any("YAML" in name for name in exc_names):
            return True

        return False

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        yaml_context = self._extract_yaml_context(context)

        title = f"YAML syntax error in {yaml_context['file_name']}"

        details_parts = []
        if yaml_context["line"] and yaml_context["column"]:
            details_parts.append(
                f"Line {yaml_context['line']}, Column {yaml_context['column']}: "
                f"{yaml_context['problem']}"
            )
        else:
            details_parts.append(yaml_context["problem"])

        if yaml_context["rendered_content"] and yaml_context["line"]:
            snippet = self._get_code_snippet(
                yaml_context["rendered_content"], yaml_context["line"], yaml_context["column"]
            )
            if snippet:
                details_parts.append("\n" + snippet)

        fix = self._get_fix_suggestion(yaml_context["problem"])

        return UserError(
            category="YAML Syntax Error",
            title=title,
            details="\n".join(details_parts),
            fix=fix,
            context={"file_path": yaml_context["file_path"]} if yaml_context["file_path"] else None,
            docs_url="https://docs.runagac.com/troubleshooting/yaml-errors",
        )

    def _extract_yaml_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract and organize YAML error context from context dict."""
        file_path = (
            context.get("file_path") or context.get("config_file") or context.get("yaml_path")
        )
        file_name = Path(file_path).name if file_path else "configuration file"

        return {
            "file_path": file_path,
            "file_name": file_name,
            "rendered_content": context.get("rendered_content"),
            "line": context.get("line"),
            "column": context.get("column"),
            "problem": context.get("problem", "syntax error"),
        }

    def _get_code_snippet(self, content: str, line_num: int, column_num: int) -> str:
        """Extract code snippet with visual indicator."""
        if not content or not line_num:
            return ""

        lines = content.split("\n")
        if line_num > len(lines):
            return ""

        start_line = max(0, line_num - 3)
        end_line = min(len(lines), line_num + 2)

        snippet_lines = []
        for i in range(start_line, end_line):
            line_content = lines[i]
            display_line_num = i + 1

            if display_line_num == line_num:
                snippet_lines.append(f"> {display_line_num:3d} | {line_content}")
                if column_num:
                    pointer = " " * (column_num - 1) + "^^"
                    snippet_lines.append(f"      | {pointer}")
            else:
                snippet_lines.append(f"  {display_line_num:3d} | {line_content}")

        return "\n".join(snippet_lines)

    def _get_fix_suggestion(self, problem: str) -> str:
        """Get concise fix suggestion based on error."""
        if not problem:
            return "Check the YAML syntax and fix any errors."

        problem_lower = problem.lower()

        fix_suggestions = {
            "expected ':'": "Missing ':' after key. Use 'key: value' syntax.",
            "could not find expected ':'": "Missing ':' after key. Use 'key: value' syntax.",
            "mapping values are not allowed": (
                "Check your indentation. Use spaces (not tabs), and ensure proper nesting."
            ),
            "expected <block end>": (
                "Check for unclosed lists or dictionaries. List items (-) must align."
            ),
            "found unexpected end of stream": (
                "File appears incomplete. Check for missing closing brackets or quotes."
            ),
            "found character '\\t'": "Remove tab characters. Use spaces for indentation.",
        }

        for pattern, suggestion in fix_suggestions.items():
            if pattern in problem_lower:
                return suggestion

        if "could not find expected" in problem_lower and "key" in problem_lower:
            return "Invalid key format. Keys must be followed by a colon (:)."

        return "Check the YAML syntax at the indicated location."
