"""Tests to ensure logging format compliance across the codebase.

These tests detect malformed logging statements that use {variable} syntax
without the f-string prefix, which results in literal {variable} being logged
instead of the variable's value.

This catches the bug pattern from issue #604:
    logger.info("Processing {item_id}")  # BAD: logs literal "{item_id}"
    logger.info(f"Processing {item_id}")  # GOOD: logs the actual value
"""

import ast
from pathlib import Path

import pytest


class LoggingFormatChecker(ast.NodeVisitor):
    """AST visitor to check logging format compliance."""

    LOGGING_METHODS = frozenset(
        {"debug", "info", "warning", "error", "critical", "exception", "log"}
    )

    def __init__(self) -> None:
        self.violations: list[dict] = []
        self.current_file: str = ""

    def visit_Call(self, node: ast.Call) -> None:
        """Check function calls for logging issues."""
        if self._is_logging_call(node):
            self._check_logging_format(node)
        self.generic_visit(node)

    def _is_logging_call(self, node: ast.Call) -> bool:
        """Check if this is a logger.method() call."""
        if isinstance(node.func, ast.Attribute):
            return node.func.attr in self.LOGGING_METHODS
        return False

    def _check_logging_format(self, node: ast.Call) -> None:
        """Check for {variable} in non-f-strings."""
        if not node.args:
            return

        first_arg = node.args[0]

        # Check for non-f-string containing {variable} syntax
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            msg = first_arg.value
            if self._has_brace_variable_pattern(msg):
                self.violations.append(
                    {
                        "file": self.current_file,
                        "line": node.lineno,
                        "message": msg[:80],
                    }
                )

    def _has_brace_variable_pattern(self, s: str) -> bool:
        """Check if string contains {identifier} or {expression} pattern."""
        import re

        # Match {identifier}, {expression}, {method()}, {obj.attr}
        pattern = r"\{[a-zA-Z_][a-zA-Z0-9_\.()]*\}"
        return bool(re.search(pattern, s))


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


class TestLoggingFormatCompliance:
    """Test suite for logging format validation."""

    def test_no_malformed_logging_in_codebase(self) -> None:
        """Verify no logging statements have {var} without f-string prefix.

        This catches the critical bug where logging like:
            logger.info("Processing {item}")
        logs the literal string "{item}" instead of the variable value.
        """
        checker = LoggingFormatChecker()
        project_root = get_project_root()
        agent_actions_dir = project_root / "agent_actions"

        if not agent_actions_dir.exists():
            pytest.skip("agent_actions directory not found")

        for py_file in agent_actions_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                checker.current_file = str(py_file.relative_to(project_root))
                checker.visit(tree)
            except SyntaxError:
                continue  # Skip files with syntax errors

        if checker.violations:
            violation_messages = [
                f"  {v['file']}:{v['line']}: {v['message']}"
                for v in checker.violations
            ]
            pytest.fail(
                f"Found {len(checker.violations)} malformed logging statement(s):\n"
                + "\n".join(violation_messages)
                + "\n\nFix by adding 'f' prefix to make f-strings."
            )

    def test_detector_catches_malformed_pattern(self) -> None:
        """Verify the checker correctly detects malformed patterns."""
        checker = LoggingFormatChecker()

        # Code with malformed logging
        bad_code = '''
logger.info("Processing {item_id}")
logger.debug("Value is {value}")
logger.error("Error in {module}: {error}")
'''
        tree = ast.parse(bad_code)
        checker.current_file = "test.py"
        checker.visit(tree)

        assert len(checker.violations) == 3, (
            f"Expected 3 violations, got {len(checker.violations)}"
        )

    def test_detector_allows_correct_patterns(self) -> None:
        """Verify the checker allows correct logging patterns."""
        checker = LoggingFormatChecker()

        # Code with correct logging
        good_code = '''
logger.info(f"Processing {item_id}")
logger.debug("Processing item: %s", item_id)
logger.error("Static message without variables")
logger.warning("Format spec {:d} is ok", value)
'''
        tree = ast.parse(good_code)
        checker.current_file = "test.py"
        checker.visit(tree)

        assert len(checker.violations) == 0, (
            f"Expected 0 violations, got {checker.violations}"
        )
