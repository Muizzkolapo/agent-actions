"""Only a workflow run starts a new events.json.

``agac run`` and ``agac retry`` pass ``new_run=True`` so the previous run rotates to
``events.1.json``. ``agac batch`` logs into the same directory and must append: if
it rotated, a few status polls would push every real run out of retention.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _new_run_values(module_path: str) -> list[object]:
    """The ``new_run`` value of each ``LoggerFactory.initialize(output_dir=...)`` call."""
    tree = ast.parse(Path(module_path).read_text())
    values = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "initialize"
            and getattr(node.func.value, "id", "") == "LoggerFactory"
        ):
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords}
        if "output_dir" not in keywords:
            continue
        value = keywords.get("new_run")
        values.append(value.value if isinstance(value, ast.Constant) else value)
    return values


@pytest.mark.parametrize("module_path", ["agent_actions/cli/run.py", "agent_actions/cli/retry.py"])
def test_a_workflow_run_starts_a_new_log_file(module_path):
    assert _new_run_values(module_path) == [True]


def test_a_batch_command_appends_to_the_current_log_file():
    assert _new_run_values("agent_actions/llm/batch/batch_cli.py") == [None]
