"""An `agac inspect` error names the action it is about, never the action the user typed."""

from __future__ import annotations

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_render_error_names_the_workflow import _project

_EDITS = {
    "about_another_action": ("    kind: tool\n", "    kind: tool\n    versions: {}\n"),
    "about_no_action": ("  - name: pick\n    kind: tool\n", "  - kind: tool\n"),
}


def _inspect(tmp_path, case: str, command: str) -> list[str]:
    root = _project(tmp_path, "schema")
    config = root / "agent_workflow" / "w" / "agent_config" / "w.yml"
    text = config.read_text().replace("rows: \"array[object:['q', 'n']]\"", 'rows: "string"')
    old, new = _EDITS[case]
    assert old in text
    config.write_text(text.replace(old, new, 1))

    result = run_agac(root, "inspect", command, "-a", "w", "typed_action")
    assert result.returncode == 1, result.stdout + result.stderr
    return (result.stdout + result.stderr).splitlines()


@pytest.mark.parametrize("command", ["action", "context"])
def test_an_error_about_another_action_names_that_action(tmp_path, command):
    lines = _inspect(tmp_path, "about_another_action", command)

    assert "  Agent: w" in lines
    assert "  Action: pick" in lines
    assert "  Action: typed_action" not in lines


@pytest.mark.parametrize("command", ["action", "context"])
def test_an_error_about_no_action_prints_no_action_line(tmp_path, command):
    lines = _inspect(tmp_path, "about_no_action", command)

    assert "  Agent: w" in lines
    assert not any(line.startswith("  Action:") for line in lines)
