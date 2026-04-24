"""Grep-based architectural tests enforcing RecordEnvelope as the single
authority for record content assembly.

These tests scan the source tree for patterns that bypass RecordEnvelope.
They act as a CI gate — if a new module manually builds content dicts,
these tests fail before the PR can merge.
"""

import subprocess
from pathlib import Path

AGENT_ACTIONS = str(Path(__file__).resolve().parents[3] / "agent_actions")


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
    """wrap_content() should only exist in content.py (as alias) and tests."""

    def test_no_wrap_content_outside_alias(self):
        count, lines = _grep_count(
            r"wrap_content\(",
            AGENT_ACTIONS,
        )
        filtered = [
            line
            for line in lines.splitlines()
            if "content.py" not in line and "_MANIFEST" not in line
        ]
        assert not filtered, "Found wrap_content() calls outside content.py:\n" + "\n".join(
            filtered
        )


class TestNoUnknownFallbacks:
    """'or \"unknown\"' hides missing data — use 'or \"NOT_SET\"' instead."""

    def test_no_or_unknown_pattern(self):
        count, lines = _grep_count(
            r'or "unknown"',
            AGENT_ACTIONS,
        )
        assert count == 0, f"Found {count} 'or \"unknown\"' pattern(s):\n{lines}"


class TestNoDeadMergePassthroughFields:
    """merge_passthrough_fields was removed from scope_application.py."""

    def test_merge_passthrough_fields_removed(self):
        import inspect

        from agent_actions.prompt.context import scope_application

        source = inspect.getsource(scope_application)
        assert "def merge_passthrough_fields" not in source, (
            "Dead function merge_passthrough_fields still exists in scope_application.py"
        )
