"""A workflow the docs site shows reads only what it depends on, and its HITL actions load.

Each block is loaded as `agac run` loads it and put to two refusals of its pre-flight:
naming an action that is not upstream through `dependencies`, and reading at FILE
granularity with no `dependencies`. They are called on their own because a fragment
leaves out the `context_scope` and schema fields the rest of pre-flight asks for. An
intent, a prompt, a tool's impl and a schema are filled in, and an action a block names
without showing stands in. A block the loader refuses for another reason is skipped:
the pages also show configurations that are wrong on purpose, and YAML that is no workflow.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig
from agent_actions.errors import ConfigurationError, ConfigValidationError
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.validation.dep_observe_validator import find_reads_not_upstream
from agent_actions.workflow.schema_service import WorkflowSchemaService
from tests.unit.skills.test_a_skill_block_passes_preflight import _project, _upstream

_REPO = Path(__file__).resolve().parents[3]
_DOCS = _REPO / "docs.agent-actions" / "docs"
_FENCE = re.compile(r"^```yaml\n(.*?)^```", re.S | re.M)
_FIRST_FILE = "reads at FILE granularity but declares no 'dependencies'"


def _blocks() -> list[Any]:
    found = []
    for page in sorted(_DOCS.rglob("*.md*")):
        text = page.read_text(encoding="utf-8")
        for match in _FENCE.finditer(text):
            try:
                block = yaml.safe_load(match.group(1))
            except yaml.YAMLError:
                continue
            if isinstance(block, dict):
                block = block.get("actions")
            if (
                isinstance(block, list)
                and block
                and all(isinstance(a, dict) and "name" in a for a in block)
            ):
                line = text.count("\n", 0, match.start()) + 1
                found.append(pytest.param(block, id=f"{page.relative_to(_DOCS)}:{line}"))
    return found


def _authored(action: dict[str, Any]) -> dict[str, Any]:
    action = dict(action)
    action.setdefault("intent", action["name"])
    kind = action.get("kind", "llm")
    if kind == "tool":
        action.setdefault("impl", action["name"])
        if not isinstance(action.get("schema"), dict):
            action["schema"] = {"out": "string"}
    elif kind != "hitl":
        if not isinstance(action.get("prompt"), str) or action["prompt"].startswith("$"):
            action["prompt"] = "Answer."
        if not isinstance(action.get("schema"), dict):
            action.pop("schema", None)
    return action


def _loaded(root: Path, block: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    _project(root, [], {})
    path = root / "agent_workflow" / "snippet" / "agent_config" / "snippet.yml"
    config = yaml.safe_load(path.read_text())
    config["actions"] = _upstream(block, {}) + [_authored(a) for a in block]
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    try:
        return WorkflowInspector("snippet", project_root=root).load()
    except (ConfigurationError, ConfigValidationError) as refused:
        pytest.skip(f"the loader refuses it: {refused}")


def _first_file_refusals(root: Path, actions: dict[str, dict[str, Any]]) -> list[str]:
    service = WorkflowSchemaService.from_action_configs(
        "snippet", actions, project_root=root, with_udf_registry=True
    )
    return [e.message for e in service.validate().errors if _FIRST_FILE in e.message]


def test_the_docs_show_workflows():
    assert len(_blocks()) >= 100


def test_preflight_refuses_a_first_action_that_reads_a_file(tmp_path):
    actions = _loaded(tmp_path, [{"name": "merge", "kind": "tool", "granularity": "file"}])
    (refusal,) = _first_file_refusals(tmp_path, actions)
    assert "'merge'" in refusal


@pytest.mark.parametrize("block", _blocks())
def test_no_block_names_an_action_it_does_not_depend_on(block, tmp_path):
    assert find_reads_not_upstream(_loaded(tmp_path, block)) == []


@pytest.mark.parametrize("block", _blocks())
def test_no_block_reads_a_file_with_no_dependencies(block, tmp_path):
    assert _first_file_refusals(tmp_path, _loaded(tmp_path, block)) == []


@pytest.mark.parametrize("block", _blocks())
def test_a_hitl_action_shows_the_settings_the_loader_requires(block):
    refused = []
    for action in block:
        if action.get("kind") == "hitl":
            try:
                ActionConfig(**{"intent": action["name"], **action})
            except ValidationError as error:
                refused.append(f"{action['name']}: {error}")
    assert refused == []
