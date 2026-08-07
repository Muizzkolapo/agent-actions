"""Grep-based architectural tests enforcing RecordEnvelope as the single
authority for record content assembly.

These tests scan the source tree for patterns that bypass RecordEnvelope.
They act as a CI gate — if a new module manually builds content dicts,
these tests fail before the PR can merge.
"""

import subprocess
from pathlib import Path

AGENT_ACTIONS = str(Path(__file__).resolve().parents[3] / "agent_actions")


def _is_inside_docstring(file_path: str, line_no: int) -> bool:
    """Check if a given line is inside a triple-quoted docstring."""
    try:
        with open(file_path) as f:
            lines = f.readlines()
    except OSError:
        return False
    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                continue
            in_docstring = not in_docstring
        if i == line_no:
            return in_docstring
    return False


def _grep_count(pattern: str, path: str, *exclude_globs: str) -> tuple[int, str]:
    """Return (match_count, matching_lines) using grep."""
    cmd = ["grep", "-rn", "-P", pattern, path, "--include=*.py"]
    for glob in exclude_globs:
        cmd.extend(["--exclude", glob])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 0, ""
    lines = result.stdout.strip()
    count = len(lines.splitlines()) if lines else 0
    return count, lines


class TestNoManualContentAssembly:
    """No module should spread **existing_content outside RecordEnvelope."""

    def test_no_existing_content_spreading(self):
        count, lines = _grep_count(
            r"\*\*existing_content",
            AGENT_ACTIONS,
        )
        # Only allowed in record/envelope.py
        filtered = [line for line in lines.splitlines() if "record/envelope" not in line]
        assert not filtered, "Found **existing_content outside record/envelope.py:\n" + "\n".join(
            filtered
        )


class TestNoDirectWrapContentCalls:
    """Content is built via RecordEnvelope.build_content; no wrap_content() anywhere."""

    def test_no_wrap_content_calls(self):
        count, lines = _grep_count(
            r"wrap_content\(",
            AGENT_ACTIONS,
        )
        filtered = [line for line in lines.splitlines() if "_MANIFEST" not in line]
        assert not filtered, "Found wrap_content() calls:\n" + "\n".join(filtered)


class TestNoUnknownFallbacks:
    """'or \"unknown\"' hides missing data — use 'or \"NOT_SET\"' instead."""

    def test_no_or_unknown_pattern(self):
        count, lines = _grep_count(
            r'or "unknown"',
            AGENT_ACTIONS,
        )
        assert count == 0, f"Found {count} 'or \"unknown\"' pattern(s):\n{lines}"


class TestNoPrintInLibraryCode:
    """Library code must use logging, not print(). Only docstring examples are allowed."""

    def test_no_bare_print_calls(self):
        cmd = [
            "grep",
            "-rn",
            "-P",
            r"^\s+print\(",
            AGENT_ACTIONS,
            "--include=*.py",
            "--exclude=safe_format.py",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return
        hits = []
        for line in result.stdout.strip().splitlines():
            if ">>>" in line or "docstring" in line or "Example" in line:
                continue
            # Bundled skill payload — standalone helpers shipped via
            # `agac skills install`, not framework library code. They need to
            # print to the user's terminal.
            if "/skills/agac-agent-skills/scripts/" in line:
                continue
            parts = line.split(":", 2)
            if len(parts) >= 2 and _is_inside_docstring(parts[0], int(parts[1])):
                continue
            hits.append(line)
        assert len(hits) == 0, f"Found {len(hits)} print() call(s) in library code:\n" + "\n".join(
            hits
        )


class TestNoDeadMergePassthroughFields:
    """merge_passthrough_fields was removed from scope_application.py."""

    def test_merge_passthrough_fields_removed(self):
        import inspect

        from agent_actions.prompt.context import scope_application

        source = inspect.getsource(scope_application)
        assert "def merge_passthrough_fields" not in source, (
            "Dead function merge_passthrough_fields still exists in scope_application.py"
        )
