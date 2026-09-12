"""The run's logging re-init must not overwrite the verbosity the CLI flags set.

``agac run`` and ``agac retry`` re-initialize with ``force=True`` to attach the
run's file handlers. ``LoggerFactory`` only remembers ``verbose``/``quiet`` for
calls that omit them, so passing either here silently restores the defect where
``--debug``, ``-v`` and ``-q`` had no effect on the run itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REINIT_MODULES = ["agent_actions/cli/run.py", "agent_actions/cli/retry.py"]


def _reinit_calls(module_path: str) -> list[set[str]]:
    tree = ast.parse(Path(module_path).read_text())
    return [
        {kw.arg for kw in node.keywords}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "initialize"
        and getattr(node.func.value, "id", "") == "LoggerFactory"
        and any(kw.arg == "output_dir" for kw in node.keywords)
    ]


@pytest.mark.parametrize("module_path", REINIT_MODULES)
def test_the_run_reinit_passes_neither_verbose_nor_quiet(module_path):
    calls = _reinit_calls(module_path)

    assert calls, f"no LoggerFactory.initialize(output_dir=...) call in {module_path}"
    for keywords in calls:
        assert "verbose" not in keywords
        assert "quiet" not in keywords
