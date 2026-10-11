"""A workflow the docs site shows reads only what it depends on, and its HITL actions load.

Each block is loaded as `agac run` loads it and put to two refusals of its pre-flight:
naming an action that is not upstream through `dependencies`, and reading at FILE
granularity with no `dependencies`. They are called on their own because a fragment
leaves out the `context_scope` and schema fields the rest of pre-flight asks for. An
intent, a prompt, a tool's impl and a schema are filled in, and an action a block names
without showing stands in. A block the loader refuses for another reason is named in
`_NOT_LOADED`; any other block it refuses fails.
"""

from __future__ import annotations

import re
import textwrap
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
_FENCE = re.compile(r"^[ \t]*```yaml\n(.*?)^[ \t]*```", re.S | re.M)
_PROMPT_NAME = re.compile(r"{[{%][^}]*?\b([A-Za-z_]\w*)\.[A-Za-z_]")
_NOT_ACTIONS = {"source", "seed", "version", "workflow", "loop"}
_FIRST_FILE = "reads at FILE granularity but declares no 'dependencies'"

# Blocks the loader refuses for a reason other than the two this test is about,
# by page and the actions shown.
_NOT_LOADED = {
    "guides/troubleshooting.md::generate_report+generate_report": "shows the wrong form beside the right one",
    "reference/validation/index.md::action_a+action_b": "shows a circular dependency",
    "reference/cli/expect.md::Check output quality": "a CI step, not a workflow",
    "reference/data-io/data-lineage.md::prepare+gpt4_answer+claude_answer+gemini_answer+best_answer": "model_vendor: google is not a vendor",
    "reference/configuration/index.md::extract_facts": "data_source on an action is refused",
    "reference/data-io/index.md::extract_facts": "data_source on an action is refused",
    "reference/prompts/dispatch.md::generate_question": "add_dispatch on an action is refused",
}


class _AsWritten(yaml.SafeDumper):
    """Keeps a prompt of several lines a block scalar, as the page writes it."""


def _text(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_AsWritten.add_representer(str, _text)


def _blocks() -> list[Any]:
    found = []
    for page in sorted(_DOCS.rglob("*.md*")):
        text = page.read_text(encoding="utf-8")
        name = str(page.relative_to(_DOCS))
        for match in _FENCE.finditer(text):
            try:
                block = yaml.safe_load(textwrap.dedent(match.group(1)))
            except yaml.YAMLError:
                continue
            defaults: dict[str, Any] = {}
            if isinstance(block, dict):
                shown = block.get("defaults")
                defaults = shown if isinstance(shown, dict) else {}
                block = block.get("actions")
            if (
                isinstance(block, list)
                and block
                and all(isinstance(a, dict) and "name" in a for a in block)
            ):
                line = text.count("\n", 0, match.start()) + 1
                shown_as = (block, defaults, f"{name}::{'+'.join(a['name'] for a in block)}")
                found.append(pytest.param(shown_as, id=f"{name}:{line}"))
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


def _stand_ins(block: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Actions *block* names without showing, a prompt's names among them.

    A name that is one version of an action the block shows is that action's, not a stand-in.
    """
    branches = tuple(f"{a['name']}_" for a in block if a.get("versions"))
    stand_ins = [a for a in _upstream(block, {}) if not a["name"].startswith(branches)]
    known = {a["name"] for a in [*stand_ins, *block]} | _NOT_ACTIONS
    prompts = " ".join(a["prompt"] for a in block if isinstance(a.get("prompt"), str))
    in_prompts = [n for n in dict.fromkeys(_PROMPT_NAME.findall(prompts)) if n not in known]
    in_prompts = [n for n in in_prompts if not n.startswith(branches)]
    return [
        _authored({"name": n, "context_scope": {"observe": ["source.*"]}}) for n in in_prompts
    ] + stand_ins


def _loaded(root: Path, shown_as: Any) -> dict[str, dict[str, Any]]:
    block, defaults, key = shown_as
    _project(root, [], {})
    path = root / "agent_workflow" / "snippet" / "agent_config" / "snippet.yml"
    config = yaml.safe_load(path.read_text())
    if "granularity" in defaults:
        config["defaults"]["granularity"] = defaults["granularity"]
    config["actions"] = _stand_ins(block) + [_authored(a) for a in block]
    path.write_text(yaml.dump(config, Dumper=_AsWritten, sort_keys=False, allow_unicode=True))
    try:
        return WorkflowInspector("snippet", project_root=root).load()
    except (ConfigurationError, ConfigValidationError):
        if key in _NOT_LOADED:
            pytest.skip(f"the loader refuses it: {_NOT_LOADED[key]}")
        raise


def _first_file_refusals(root: Path, actions: dict[str, dict[str, Any]]) -> list[str]:
    service = WorkflowSchemaService.from_action_configs(
        "snippet", actions, project_root=root, with_udf_registry=True
    )
    return [e.message for e in service.validate().errors if _FIRST_FILE in e.message]


def test_the_docs_show_workflows():
    assert len(_blocks()) >= 100


def test_preflight_refuses_a_first_action_that_reads_a_file(tmp_path):
    block = [{"name": "merge", "kind": "tool", "granularity": "file"}]
    actions = _loaded(tmp_path, (block, {}, "here"))
    (refusal,) = _first_file_refusals(tmp_path, actions)
    assert "'merge'" in refusal


def test_every_block_left_unloaded_is_shown():
    shown = {param.values[0][2] for param in _blocks()}
    assert set(_NOT_LOADED) - shown == set()


@pytest.mark.parametrize("shown_as", _blocks())
def test_no_block_names_an_action_it_does_not_depend_on(shown_as, tmp_path):
    assert find_reads_not_upstream(_loaded(tmp_path, shown_as)) == []


@pytest.mark.parametrize("shown_as", _blocks())
def test_no_block_reads_a_file_with_no_dependencies(shown_as, tmp_path):
    assert _first_file_refusals(tmp_path, _loaded(tmp_path, shown_as)) == []


@pytest.mark.parametrize("shown_as", _blocks())
def test_a_hitl_action_shows_the_settings_the_loader_requires(shown_as):
    refused = []
    for action in shown_as[0]:
        if action.get("kind") == "hitl":
            try:
                ActionConfig(**{"intent": action["name"], **action})
            except ValidationError as error:
                refused.append(f"{action['name']}: {error}")
    assert refused == []
