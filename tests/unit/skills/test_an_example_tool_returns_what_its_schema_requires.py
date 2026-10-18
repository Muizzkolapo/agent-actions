"""Each example's tool returns, on every return, every field its action's schema requires.

The tool modules under `examples/*/tools` are paired with the schema the action running
them names in the example's workflow, and put to pre-flight's required-key check, so a
copied example passes pre-flight.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from agent_actions.validation.udf_required_field_validator import (
    find_conditional_required_field_risks,
)
from tests.unit.skills.test_a_docs_tool_returns_what_its_schema_requires import (
    _required,
    _workflow_actions,
)

_EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def _pairs() -> list[Any]:
    found = []
    for example in sorted(p for p in _EXAMPLES.iterdir() if (p / "tools").is_dir()):
        actions = _workflow_actions(example)
        for module in sorted((example / "tools").rglob("*.py")):
            source = module.read_text(encoding="utf-8")
            for func in ast.parse(source).body:
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for action in actions:
                    if action["impl"] != func.name:
                        continue
                    required = _required(action["schema"], action["name"], example)
                    if not required:
                        continue
                    found.append(
                        pytest.param(
                            action["name"],
                            ast.get_source_segment(source, func),
                            required,
                            id=f"{module.relative_to(_EXAMPLES)}:{func.name}",
                        )
                    )
    return found


def test_the_incident_triage_aggregator_is_paired_with_its_schema():
    ids = {param.id for param in _pairs()}
    module = "incident_triage/tools/incident_triage/aggregate_severity_votes.py"
    assert f"{module}:aggregate_severity_votes" in ids


@pytest.mark.parametrize(("action", "shown", "required"), _pairs())
def test_an_example_tool_returns_every_field_its_schema_requires(action, shown, required):
    assert (
        find_conditional_required_field_risks({action: {"source": shown, "required": required}})
        == []
    )
