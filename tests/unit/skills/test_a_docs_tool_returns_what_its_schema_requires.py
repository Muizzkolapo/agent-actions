"""Tool code a page shows returns every field the schema it goes with requires.

A tool's function goes with a schema when an action that runs it as its `impl` names
one: in a YAML block on the same page, or, for an example's page, in that example's
workflow. A schema written inline or kept in the example's `schema/` directory is
compiled as the loader compiles it, and the function is put to pre-flight's
required-key check. A tool that leaves a required field out fails every record, and
pre-flight refuses it.
"""

from __future__ import annotations

import ast
import re
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.validation.udf_required_field_validator import (
    find_conditional_required_field_risks,
)

_REPO = Path(__file__).resolve().parents[3]
_PAGES = sorted(
    [
        *(_REPO / "docs.agent-actions" / "docs").rglob("*.md*"),
        *(_REPO / "examples").rglob("*.md"),
        *(_REPO / "agent_actions" / "skills").rglob("*.md"),
    ]
)
_PYTHON = re.compile(r"^[ \t]*```python[^\n]*\n(.*?)^[ \t]*```", re.S | re.M)
_YAML = re.compile(r"^[ \t]*```ya?ml[^\n]*\n(.*?)^[ \t]*```", re.S | re.M)


def _actions_in(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if isinstance(node.get("impl"), str) and node.get("schema") is not None:
            yield node
        for value in node.values():
            yield from _actions_in(value)
    elif isinstance(node, list):
        for value in node:
            yield from _actions_in(value)


def _page_actions(text: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for match in _YAML.finditer(text):
        try:
            found += _actions_in(yaml.safe_load(textwrap.dedent(match.group(1))))
        except yaml.YAMLError:
            continue
    return found


def _example(page: Path) -> Path | None:
    parts = page.relative_to(_REPO).parts
    return _REPO / "examples" / parts[1] if parts[0] == "examples" else None


def _workflow_actions(example: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for config in sorted(example.rglob("agent_config/*.yml")):
        found += _actions_in(yaml.safe_load(config.read_text(encoding="utf-8")))
    return found


def _required(schema: Any, action: str, example: Path | None) -> list[str] | None:
    if isinstance(schema, str):
        files = sorted(example.rglob(f"schema/**/{schema}.yml")) if example else []
        if not files:
            return None
        schema = yaml.safe_load(files[0].read_text(encoding="utf-8"))
    if isinstance(schema, list):
        schema = {"name": action, "fields": schema}
    elif isinstance(schema, dict):
        schema = {"name": action, **schema}
    else:
        return None
    compiled = compile_unified_schema(schema, "openai")
    assert isinstance(compiled, dict)
    return list(compiled.get("schema", compiled).get("required") or [])


def _pairs() -> list[Any]:
    """One per function a page shows and the schema an action running it names."""
    found = []
    for page in _PAGES:
        text = page.read_text(encoding="utf-8")
        example = _example(page)
        actions = _page_actions(text) + (_workflow_actions(example) if example else [])
        for match in _PYTHON.finditer(text):
            source = textwrap.dedent(match.group(1))
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            line = text.count("\n", 0, match.start()) + 1
            for func in tree.body:
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for action in actions:
                    if action["impl"] != func.name:
                        continue
                    required = _required(action["schema"], action["name"], example)
                    if not required:
                        continue
                    shown = ast.get_source_segment(source, func)
                    found.append(
                        pytest.param(
                            action["name"],
                            shown,
                            required,
                            id=f"{page.relative_to(_REPO)}:{line}:{func.name}",
                        )
                    )
    return found


def test_the_incident_triage_patterns_are_paired_with_their_schemas():
    ids = {param.id for param in _pairs()}
    page = "examples/incident_triage/docs/PATTERNS.md"
    for tool in ("aggregate_severity_votes", "assign_team_based_on_impact"):
        assert any(i.startswith(page) and i.endswith(f":{tool}") for i in ids), tool
    assert any(i.startswith(page) and i.endswith(":format_incident_triage") for i in ids)


def test_a_tool_that_leaves_out_a_required_field_is_found():
    shown = 'def t(data):\n    return [{"incident": {}, "teams": {}}]\n'
    findings = find_conditional_required_field_risks(
        {"format": {"source": shown, "required": ["triage_id", "incident", "teams"]}}
    )
    assert len(findings) == 1 and "'triage_id'" in findings[0]


@pytest.mark.parametrize(("action", "shown", "required"), _pairs())
def test_a_shown_tool_returns_every_field_its_schema_requires(action, shown, required):
    assert (
        find_conditional_required_field_risks({action: {"source": shown, "required": required}})
        == []
    )
