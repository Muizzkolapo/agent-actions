#!/usr/bin/env python3
"""Check for malformed logging statements using AST parsing.

This script detects logging statements that use {variable} syntax without
the f-string prefix, which results in literal {variable} being logged
instead of the variable's value.

Usage:
    python scripts/check_logging_format.py [path...]

Examples:
    python scripts/check_logging_format.py agent_actions
    python scripts/check_logging_format.py agent_actions/cli/main.py
"""

import ast
import sys
from pathlib import Path
from typing import NamedTuple


class LoggingIssue(NamedTuple):
    """Represents a logging format issue found in the code."""

    file: str
    line: int
    col: int
    message: str
    code: str


class LoggingFormatChecker(ast.NodeVisitor):
    """AST visitor to detect malformed logging statements."""

    LOGGING_METHODS = frozenset(
        {"debug", "info", "warning", "error", "critical", "exception", "log"}
    )

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.issues: list[LoggingIssue] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Visit function calls and check for logging issues."""
        if self._is_logging_call(node):
            self._check_logging_format(node)
        self.generic_visit(node)

    def _is_logging_call(self, node: ast.Call) -> bool:
        """Check if this is a logger.method() call."""
        if isinstance(node.func, ast.Attribute):
            return node.func.attr in self.LOGGING_METHODS
        return False

    def _check_logging_format(self, node: ast.Call) -> None:
        """Check the logging call for format issues."""
        if not node.args:
            return

        first_arg = node.args[0]

        # Issue 1: Non-f-string containing {variable} syntax
        # This is the main bug from issue #604
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            msg = first_arg.value
            if self._has_brace_pattern(msg):
                self.issues.append(
                    LoggingIssue(
                        file=self.filepath,
                        line=node.lineno,
                        col=node.col_offset,
                        message=f"Logging contains {{variable}} but is not an f-string: {msg[:50]}...",
                        code="LOG-FMT-001",
                    )
                )

            # Issue 2: Mixed formatting (both {var} and %s in same string)
            if "{" in msg and "%" in msg and not msg.startswith("%("):
                # Exclude structured logging format strings like %(message)s
                self.issues.append(
                    LoggingIssue(
                        file=self.filepath,
                        line=node.lineno,
                        col=node.col_offset,
                        message=f"Logging mixes {{variable}} and %s formatting: {msg[:50]}...",
                        code="LOG-FMT-002",
                    )
                )

    def _has_brace_pattern(self, s: str) -> bool:
        """Check if string contains {identifier} or {expression} pattern.

        This looks for patterns like {var}, {len(x)}, {self.name} that
        suggest f-string syntax was intended but the f prefix was forgotten.
        """
        import re

        # Match {identifier}, {expression}, {method()}, {obj.attr}
        # but exclude empty braces {}, format specs like {:d}, and dict literals
        pattern = r"\{[a-zA-Z_][a-zA-Z0-9_\.()]*\}"
        return bool(re.search(pattern, s))


def check_file(filepath: Path) -> list[LoggingIssue]:
    """Check a single Python file for logging format issues."""
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
        checker = LoggingFormatChecker(str(filepath))
        checker.visit(tree)
        return checker.issues
    except SyntaxError as e:
        print(f"Syntax error in {filepath}: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Error processing {filepath}: {e}", file=sys.stderr)
        return []


def check_path(path: Path) -> list[LoggingIssue]:
    """Check a file or directory for logging format issues."""
    all_issues: list[LoggingIssue] = []

    if path.is_file():
        if path.suffix == ".py":
            all_issues.extend(check_file(path))
    elif path.is_dir():
        for py_file in path.rglob("*.py"):
            all_issues.extend(check_file(py_file))

    return all_issues


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python check_logging_format.py <path> [path...]", file=sys.stderr)
        print("Example: python check_logging_format.py agent_actions", file=sys.stderr)
        return 1

    all_issues: list[LoggingIssue] = []

    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"Path does not exist: {path}", file=sys.stderr)
            continue
        all_issues.extend(check_path(path))

    if all_issues:
        print(f"\nFound {len(all_issues)} logging format issue(s):\n")
        for issue in sorted(all_issues, key=lambda x: (x.file, x.line)):
            print(f"{issue.file}:{issue.line}:{issue.col}")
            print(f"  [{issue.code}] {issue.message}")
            print()
        return 1

    print("No logging format issues found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
