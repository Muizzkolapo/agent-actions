"""A workflow the docs or an example's pages show reads only what it depends on, and loads.

Each block is loaded as `agac run` loads it and put to three refusals of its pre-flight:
naming an action that is not upstream through `dependencies`, in a guard, a prompt or
any part of its context scope, and reading at FILE granularity with no `dependencies`. They are called on their own because a fragment
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
_PAGES = sorted(
    [
        *(_REPO / "docs.agent-actions" / "docs").rglob("*.md*"),
        *(_REPO / "examples").rglob("*.md"),
    ]
)
_FENCE = re.compile(r"^[ \t]*```yaml\n(.*?)^[ \t]*```", re.S | re.M)
_PROMPT_NAME = re.compile(r"{[{%][^}]*?\b([A-Za-z_]\w*)\.[A-Za-z_]")
_NOT_ACTIONS = {"source", "seed", "version", "workflow", "loop"}
_FIRST_FILE = "reads at FILE granularity but declares no 'dependencies'"
_NOT_REACHABLE = "is not reachable from action"

# Blocks the loader refuses for a reason other than the two this test is about,
# by page and the actions shown.
_NOT_LOADED = {
    "docs.agent-actions/docs/guides/troubleshooting.md::generate_report+generate_report": "shows the wrong form beside the right one",
    "docs.agent-actions/docs/reference/validation/index.md::action_a+action_b": "shows a circular dependency",
    "docs.agent-actions/docs/reference/cli/expect.md::Check output quality": "a CI step, not a workflow",
    "docs.agent-actions/docs/reference/prompts/prompt-store.md::analyze": "loads a store prompt this project lacks",
    "docs.agent-actions/docs/reference/configuration/endpoints.md::extract+classify+review+final_check": "selects endpoints this project does not declare",
    "examples/incident_triage/docs/PATTERNS.md::validate_data+validate_data+use_validated": "shows the wrong form beside the right one",
    "examples/incident_triage/docs/PATTERNS.md::inject_data+inject_data": "shows the wrong form beside the right one",
}
# Pages with a block that lists actions and is not YAML until its template is rendered.
_TEMPLATED = {
    "docs.agent-actions/docs/reference/configuration/templates.md",
    "docs.agent-actions/docs/reference/execution/guards.md",
    "docs.agent-actions/docs/reference/validation/output-validation.md",
}


class _AsWritten(yaml.SafeDumper):
    """Keeps a prompt of several lines a block scalar, as the page writes it."""


def _text(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_AsWritten.add_representer(str, _text)


def _blocks() -> list[Any]:
    found = []
    for page in _PAGES:
        text = page.read_text(encoding="utf-8")
        name = str(page.relative_to(_REPO))
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
    if kind != "tool" and not isinstance(action.get("schema"), dict):
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


def _refusals(root: Path, actions: dict[str, dict[str, Any]], saying: str) -> list[str]:
    service = WorkflowSchemaService.from_action_configs(
        "snippet", actions, project_root=root, with_udf_registry=True
    )
    return [e.message for e in service.validate().errors if saying in e.message]


def _unparsed() -> set[str]:
    """Pages with a block that lists actions and does not parse."""
    found = set()
    for page in _PAGES:
        for match in _FENCE.finditer(page.read_text(encoding="utf-8")):
            try:
                yaml.safe_load(textwrap.dedent(match.group(1)))
            except yaml.YAMLError:
                if "- name:" in match.group(1):
                    found.add(str(page.relative_to(_REPO)))
    return found


def test_the_docs_show_workflows():
    assert len(_blocks()) >= 100


def test_preflight_refuses_a_first_action_that_reads_a_file(tmp_path):
    block = [{"name": "merge", "kind": "tool", "granularity": "file"}]
    actions = _loaded(tmp_path, (block, {}, "here"))
    (refusal,) = _refusals(tmp_path, actions, _FIRST_FILE)
    assert "'merge'" in refusal


def test_every_block_left_unloaded_is_shown():
    shown = {param.values[0][2] for param in _blocks()}
    assert set(_NOT_LOADED) - shown == set()


@pytest.mark.parametrize("shown_as", _blocks())
def test_no_block_names_an_action_it_does_not_depend_on(shown_as, tmp_path):
    assert find_reads_not_upstream(_loaded(tmp_path, shown_as)) == []


@pytest.mark.parametrize("shown_as", _blocks())
def test_no_block_reads_a_file_with_no_dependencies(shown_as, tmp_path):
    assert _refusals(tmp_path, _loaded(tmp_path, shown_as), _FIRST_FILE) == []


def test_preflight_refuses_a_drop_of_an_action_that_is_not_upstream(tmp_path):
    block = [
        {"name": "a", "context_scope": {"observe": ["source.*"]}},
        {"name": "b", "context_scope": {"observe": ["source.*"], "drop": ["a.out"]}},
    ]
    (refusal,) = _refusals(tmp_path, _loaded(tmp_path, (block, {}, "here")), _NOT_REACHABLE)
    assert "'a'" in refusal and "'b'" in refusal


@pytest.mark.parametrize("shown_as", _blocks())
def test_no_block_scopes_an_action_it_cannot_reach(shown_as, tmp_path):
    assert _refusals(tmp_path, _loaded(tmp_path, shown_as), _NOT_REACHABLE) == []


def test_every_block_that_does_not_parse_is_a_template():
    assert _unparsed() == _TEMPLATED


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
