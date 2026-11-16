"""The include read check sees the context_scope that the run gives each action."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml

from agent_actions.config.includes import _Levels
from agent_actions.config.manager import ConfigManager
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    B1,
    B2,
    INCLUDE,
    WF,
    A,
    Z,
    _names,
    _pair,
    _refusal,
    _render,
    _with,
)
from tests.unit.config.test_an_include_overrides_removes_and_sets_defaults import (
    WITH_Z,
    _include,
    _rendered,
)
from tests.unit.config.test_an_inherited_read_is_checked_at_the_branch_boundary import (
    DECLARING_Z,
    _branch_reads,
    _refusal_of,
)

READS = ("observe", "passthrough", "drop")
INHERITED_Z = {"context_scope": {"observe": ["z.text"]}}


def _branch_scoped(value) -> dict:
    return _pair(
        [
            _with(B1, context_scope={"observe": value}),
            _with(B2, context_scope={"observe": value}),
        ]
    )


class TestAnOwnDirectiveReplacesTheInheritedOne:
    @pytest.mark.parametrize("value", [None, "a.text", {"a": "text"}], ids=["null", "text", "map"])
    @pytest.mark.parametrize("level", ["workflow", "include"])
    def test_a_value_that_is_not_a_list_reads_nothing(self, tmp_path, level, value):
        include = _include(defaults=INHERITED_Z) if level == "include" else INCLUDE
        defaults = {"workflow_defaults": INHERITED_Z} if level == "workflow" else {}

        rendered = _rendered(
            tmp_path / "loads", [A, Z, include], {"pair": _branch_scoped(value)}, **defaults
        )
        message = _refusal_of(tmp_path / "control", [A, Z, include], None, **defaults)

        assert _names(rendered) == ["a", "z", "b1", "b2"]
        assert message.startswith(
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': reads 'z'"
        )


class TestAnOverrideTakesAnInheritedReadAway:
    REROUTE = {"dependencies": ["a"], "context_scope": {"observe": ["a.text"]}}
    DROP_B1 = {"context_scope": {"drop": ["b1.text"]}}

    def test_a_directive_set_to_null(self, tmp_path):
        override = {"b2": {**self.REROUTE, "context_scope": {"observe": ["a.text"], "drop": None}}}

        rendered = _render(
            tmp_path / "loads",
            [A, _include(remove=["b1"], override=override, defaults=self.DROP_B1)],
        )
        message = _refusal(
            tmp_path / "control",
            [A, _include(remove=["b1"], override={"b2": self.REROUTE}, defaults=self.DROP_B1)],
        )

        assert _names(rendered) == ["a", "b2"]
        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of branch 'pair' (branches/pair.yml), but "
            "'b2' (from 'context_scope' under 'defaults:' of include 'pair') still reads it. "
            "Remove the readers too, override them so that they do not read it, or remove the read "
            "from the defaults named above. In an override, null takes away an inherited directive, "
            "and a list is added to it."
        )

    def test_a_directive_set_to_a_list_is_added_to_the_inherited_one(self, tmp_path):
        override = {"b2": {**self.REROUTE, "context_scope": {"observe": ["a.text"], "drop": []}}}

        message = _refusal(
            tmp_path / "list",
            [A, _include(remove=["b1"], override=override, defaults=self.DROP_B1)],
        )

        assert message.startswith(
            f"Include 'pair' in {WF}: remove names 'b1' of branch 'pair' (branches/pair.yml), but "
            "'b2' (from 'context_scope' under 'defaults:' of include 'pair') still reads it."
        )


class TestAnEmptyWorkflowScopeLeavesTheProjectScope:
    UNSCOPED = {k: v for k, v in B1.items() if k != "context_scope"}

    @pytest.mark.parametrize("workflow", [None, {}], ids=["null", "empty"])
    def test_a_project_read_of_a_host_action_is_refused(self, tmp_path, workflow):
        defaults = {
            "workflow_defaults": {"context_scope": workflow},
            "project_defaults": INHERITED_Z,
        }

        message = _refusal_of(
            tmp_path / "bad", [A, Z, INCLUDE], {"pair": _pair([self.UNSCOPED, B2])}, **defaults
        )

        assert message == _branch_reads("b1", "z", "'default_agent_config:' in agent_actions.yml")
        rendered = _rendered(
            tmp_path / "good",
            [A, Z, WITH_Z],
            {"pair": _pair([self.UNSCOPED, B2], **DECLARING_Z)},
            **defaults,
        )
        assert _names(rendered) == ["a", "z", "b1", "b2"]


ABSENT = object()
PROJECT = [
    ABSENT,
    {"observe": ["source.text"]},
    {"drop": ["source.id"], "seed": {"s": "$file:s.json"}},
]
WORKFLOW = [ABSENT, None, {}, {"observe": ["source.id"], "passthrough": ["source.page"]}]
INSTANCE = [ABSENT, {"observe": ["a.x"]}, {"drop": ["a.text"]}]
OWN = [ABSENT, {"observe": None}, {"observe": "a.text"}, {"observe": ["a.y"], "drop": None}]
GRID = list(
    itertools.product(
        range(len(PROJECT)), range(len(WORKFLOW)), range(len(INSTANCE)), range(len(OWN))
    )
)


def _run_scopes(root: Path) -> dict[str, dict]:
    workflow = root / WF
    manager = ConfigManager(str(workflow), str(root / "agent_actions.yml"), project_root=root)
    manager.load_configs()
    manager.validate_agent_name()
    manager.merge_agent_configs(manager.get_user_agents())
    manager.determine_execution_order()
    return {
        name: {key: value for key, value in (config.context_scope or {}).items() if key in READS}
        for name, config in manager.agent_configs.items()
    }


@pytest.mark.parametrize("project, workflow, instance, own", GRID)
def test_the_check_computes_the_scope_the_run_gives(tmp_path, project, workflow, instance, own):
    b1 = {k: v for k, v in B1.items() if k != "context_scope"}
    if OWN[own] is not ABSENT:
        b1["context_scope"] = OWN[own]
    include = dict(INCLUDE)
    if INSTANCE[instance] is not ABSENT:
        include["defaults"] = {"context_scope": INSTANCE[instance]}
    defaults = {}
    if PROJECT[project] is not ABSENT:
        defaults["project_defaults"] = {"context_scope": PROJECT[project]}
    if WORKFLOW[workflow] is not ABSENT:
        defaults["workflow_defaults"] = {"context_scope": WORKFLOW[workflow]}
    root = tmp_path / "project"
    rendered = _rendered(root, [A, include], {"pair": _pair([b1, B2])}, **defaults)

    levels = _Levels.load(rendered, root)
    run = _run_scopes(root)

    assert levels is not None
    checked = {action["name"]: levels.scope(action) for action in rendered["actions"]}
    assert checked == run
    assert yaml.safe_load((root / WF).read_text())["name"] == "wf"
