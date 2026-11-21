"""What an included branch reads, defines and shows is held to the rules of inline actions."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.includes import expand_workflow_includes
from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.utils.udf_management.registry import UDF_REGISTRY
from agent_actions.workflow.executor import _READS_STAMPS, _compute_action_config_hash
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    B1,
    B2,
    INCLUDE,
    WF,
    A,
    C,
    Z,
    _agents,
    _names,
    _pair,
    _project,
    _refusal,
    _render,
    _with,
)

HV = _with(Z, name="hv", versions={"range": [1, 2]})
ZV = _with(Z, versions={"range": [1, 2]})
VOTE = {
    "name": "vote",
    "kind": "tool",
    "impl": "pair_vote",
    "intent": "vote",
    "schema": {"text": "string"},
    "dependencies": ["a"],
    "versions": {"range": [1, 2]},
    "context_scope": {"observe": ["a.text"]},
}
TALLY = {
    "name": "tally",
    "kind": "tool",
    "impl": "host_tally",
    "intent": "tally",
    "schema": {"text": "string"},
    "dependencies": ["vote"],
    "version_consumption": {"source": "vote", "pattern": "merge"},
    "context_scope": {"observe": ["vote.text"]},
}
B2_FROM_A = _with(B2, dependencies=["a"], context_scope={"observe": ["a.text"]})
WITH_Z = {"include": "pair", "inputs": {"a": "a", "z": "z"}}


def _judged(*refs: str) -> dict:
    return {
        "expectations": [
            {
                "type": "llm_judge",
                "field": "text",
                "params": {"context": list(refs), "criteria": "ok"},
            }
        ]
    }


def _declaring_z(actions) -> dict:
    return _pair(actions, inputs={"a": "Holds the text", "z": "Holds more"})


def _branch_reads_z(name: str) -> str:
    return (
        f"Branch 'pair' (branches/pair.yml), included in {WF}, action '{name}': reads 'z', which is not a "
        "branch action or a declared input. Declare it under 'inputs:'."
    )


def _with_defaults(tmp_path: Path, actions, branches, defaults_expect) -> dict:
    workflow = _project(tmp_path, actions, branches)
    data = yaml.safe_load(workflow.read_text())
    data["defaults"]["expect"] = defaults_expect
    workflow.write_text(yaml.safe_dump(data, sort_keys=False))
    return yaml.safe_load(
        render_pipeline_with_templates(
            workflow, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
        )
    )


class TestAnInheritedExpectCountsAsARead:
    def test_a_branch_read_of_an_undeclared_host_action_through_the_defaults(self, tmp_path):
        with pytest.raises(ConfigurationError) as caught:
            _with_defaults(tmp_path / "bad", [A, Z, INCLUDE], None, _judged("z.text"))

        assert str(caught.value) == _branch_reads_z("b1")
        rendered = _with_defaults(
            tmp_path / "good", [A, Z, WITH_Z], {"pair": _declaring_z([B1, B2])}, _judged("z.text")
        )
        assert _names(rendered) == ["a", "z", "b1", "b2"]

    def test_a_host_read_of_a_branch_internal_through_the_defaults(self, tmp_path):
        with pytest.raises(ConfigurationError) as caught:
            _with_defaults(tmp_path / "bad", [A, INCLUDE], None, _judged("b1.text"))

        assert str(caught.value) == (
            f"Action 'a' in {WF} reads 'b1', which branch 'pair' (branches/pair.yml) does not list under outputs. "
            "Outputs of 'pair': b2."
        )
        rendered = _with_defaults(tmp_path / "good", [A, INCLUDE], None, _judged("b2.text"))
        assert _names(rendered) == ["a", "b1", "b2"]

    def test_the_project_defaults_count_when_the_workflow_sets_none(self, tmp_path):
        workflow = _project(tmp_path / "bad", [A, Z, INCLUDE])
        project = tmp_path / "bad" / "agent_actions.yml"
        project.write_text(
            "schema_path: schema\n"
            + yaml.safe_dump({"default_agent_config": {"expect": _judged("z.text")}})
        )

        with pytest.raises(ConfigurationError) as caught:
            render_pipeline_with_templates(
                workflow,
                tmp_path / "templates",
                compile_schemas=False,
                project_root=tmp_path / "bad",
            )

        assert str(caught.value) == _branch_reads_z("b1")

    def test_an_action_expect_is_still_read(self, tmp_path):
        reader = _with(B2, expect=_judged("z.text"))

        message = _refusal(tmp_path / "bad", [A, Z, INCLUDE], {"pair": _pair([B1, reader])})

        assert message == _branch_reads_z("b2")
        rendered = _render(tmp_path / "good", [A, Z, WITH_Z], {"pair": _declaring_z([B1, reader])})
        assert _names(rendered) == ["a", "z", "b1", "b2"]


class TestTheClosureReadsEveryChannel:
    def test_a_version_consumption_source(self, tmp_path):
        reader = _with(B2, version_consumption={"source": "z", "pattern": "merge"})

        message = _refusal(tmp_path / "bad", [A, ZV, INCLUDE], {"pair": _pair([B1, reader])})

        assert message == _branch_reads_z("b2")
        rendered = _render(tmp_path / "good", [A, ZV, WITH_Z], {"pair": _declaring_z([B1, reader])})
        assert _names(rendered) == ["a", "z_1", "z_2", "b1", "b2"]

    def test_a_branch_reads_a_version_of_an_input_it_declares(self, tmp_path):
        reader = _with(B2, dependencies=["b1", "hv_1"])
        declared = _pair([B1, reader], inputs={"a": "Holds", "hv": "Holds versions"})

        rendered = _render(
            tmp_path / "good",
            [A, HV, {"include": "pair", "inputs": {"a": "a", "hv": "hv"}}],
            {"pair": declared},
        )

        assert _names(rendered) == ["a", "hv_1", "hv_2", "b1", "b2"]
        message = _refusal(
            tmp_path / "bad",
            [A, HV, ZV, INCLUDE],
            {"pair": _pair([B1, _with(B2, dependencies=["b1", "z_1"])])},
        )
        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b2': reads 'z_1', which is not a "
            "branch action or a declared input. Declare it under 'inputs:'."
        )


class TestAVersionedBranchActionIsOneAction:
    def test_a_host_read_of_an_internal_one_by_its_base_name(self, tmp_path):
        message = _refusal(
            tmp_path / "bad", [A, INCLUDE, TALLY], {"pair": _pair([VOTE, B2_FROM_A])}
        )

        assert message == (
            f"Action 'tally' in {WF} reads 'vote', which branch 'pair' (branches/pair.yml) does not list under "
            "outputs. Outputs of 'pair': b2."
        )
        rendered = _render(
            tmp_path / "good",
            [A, INCLUDE, TALLY],
            {"pair": _pair([VOTE, B2_FROM_A], outputs=["vote"])},
        )
        assert _names(rendered) == ["a", "vote_1", "vote_2", "b2", "tally"]

    def test_a_host_action_named_like_one_of_its_versions(self, tmp_path):
        clash = _with(Z, name="vote_2")

        message = _refusal(
            tmp_path / "bad", [A, clash, INCLUDE], {"pair": _pair([VOTE, B2_FROM_A])}
        )

        assert message == (
            f"Action name 'vote_2' is defined twice in {WF}: by workflow 'wf' and by branch "
            "'pair' (branches/pair.yml). Rename one of them."
        )
        kept = _render(tmp_path / "good", [A, Z, INCLUDE], {"pair": _pair([VOTE, B2_FROM_A])})
        assert _names(kept) == ["a", "z", "vote_1", "vote_2", "b2"]

    def test_a_host_action_named_like_its_base_name(self, tmp_path):
        versioned_b1 = _with(B1, versions={"range": [1, 2]})
        branch = _pair([versioned_b1, B2_FROM_A])

        message = _refusal(tmp_path / "bad", [A, _with(Z, name="b1"), INCLUDE], {"pair": branch})

        assert message == (
            f"Action name 'b1' is defined twice in {WF}: by workflow 'wf' and by branch "
            "'pair' (branches/pair.yml). Rename one of them."
        )
        kept = _render(tmp_path / "good", [A, Z, INCLUDE], {"pair": branch})
        assert _names(kept) == ["a", "z", "b1_1", "b1_2", "b2"]

    def test_each_version_keeps_its_origin_through_the_config_manager(self, tmp_path):
        agents = _agents(tmp_path, [A, INCLUDE], {"pair": _pair([VOTE], outputs=["vote"])})

        assert list(agents) == ["a", "vote_1", "vote_2"]
        for name in ("vote_1", "vote_2"):
            assert agents[name]["_include"] == {
                "branch": "pair",
                "instance": "pair",
                "local_name": "vote",
                "branch_file": "branches/pair.yml",
            }

    def test_a_cycle_names_the_version_that_comes_from_the_branch(self, tmp_path):
        looped = _with(A, dependencies=["vote_1"], context_scope={"observe": ["vote_1.text"]})
        with pytest.raises(ConfigurationError) as caught:
            _agents(tmp_path, [looped, INCLUDE], {"pair": _pair([VOTE], outputs=["vote"])})
        messages = [error["message"] for error in caught.value.context["validation_errors"]]

        assert messages == [
            "Value error, Circular dependency detected: a -> vote_1 -> a. "
            "'vote_1' comes from branch 'pair' (branches/pair.yml)."
        ]


class TestAWrittenOriginIsRefused:
    def test_in_a_workflow_with_no_include(self, tmp_path):
        message = _refusal(tmp_path / "bad", [_with(A, _include={"branch": "pair"}), Z], {})

        assert message == (
            f"Action 'a' in {WF}: '_include' is set by the load on an included action and "
            "cannot be written in a workflow."
        )
        assert _names(_render(tmp_path / "good", [A, Z], {})) == ["a", "z"]

    def test_in_a_workflow_with_an_include(self, tmp_path):
        message = _refusal(tmp_path, [_with(A, _include={"instance": "zz"}), INCLUDE])

        assert message == (
            f"Action 'a' in {WF}: '_include' is set by the load on an included action and "
            "cannot be written in a workflow."
        )

    def test_in_a_branch_file(self, tmp_path):
        written = _pair([_with(B1, _include={"instance": "zz"}), B2])

        message = _refusal(tmp_path, [A, INCLUDE], {"pair": written})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': '_include' is set by the load on "
            "an included action and cannot be written in a branch file."
        )


class TestANamedSchemaLoadsInABranch:
    def test_schema_name_loads_as_it_does_inline(self, tmp_path):
        named = {k: v for k, v in B1.items() if k != "schema"} | {"schema_name": "pair_note"}
        for root in (tmp_path / "inline", tmp_path / "included"):
            (root / "schema").mkdir(parents=True)
            (root / "schema" / "pair_note.yml").write_text(
                "name: pair_note\nfields:\n  - id: text\n    type: string\n"
            )

        inline = _agents(tmp_path / "inline", [A, named, B2, C])
        included = _agents(tmp_path / "included", [A, INCLUDE, C], {"pair": _pair([named, B2])})

        assert included["b1"]["json_output_schema"] == inline["b1"]["json_output_schema"]
        assert _compute_action_config_hash(included["b1"]) == _compute_action_config_hash(
            inline["b1"]
        )


class TestJinjaIsRefusedAtAnyDepth:
    def test_a_nested_value(self, tmp_path):
        guarded = _with(B1, guard={"condition": "{{ x }} == 1", "on_false": "filter"})

        message = _refusal(tmp_path / "bad", [A, INCLUDE], {"pair": _pair([guarded, B2])})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': 'guard' holds Jinja. "
            "A branch file is plain YAML and is not rendered."
        )
        plain = _with(B1, guard={"condition": "a.text == 1", "on_false": "filter"})
        assert _names(_render(tmp_path / "good", [A, INCLUDE], {"pair": _pair([plain, B2])})) == [
            "a",
            "b1",
            "b2",
        ]


TWIN = _pair([_with(B1, impl="twin_one")], branch="twin", outputs=[])
TWIN_OK = _pair([_with(B1, name="t1", impl="twin_one")], branch="twin", outputs=[])
TWIN_INCLUDE = {"include": "twin", "inputs": {"a": "a"}}


@pytest.mark.parametrize(
    "bad, good, expected",
    [
        (
            ([A, {**INCLUDE, "as": "left"}], None),
            ([A, INCLUDE], None),
            f"Include 'pair' in {WF}: key 'as' is not supported yet. "
            "Include keys: include, inputs, defaults, override, remove.",
        ),
        (
            ([A, INCLUDE, TWIN_INCLUDE], {"pair": _pair(), "twin": TWIN}),
            ([A, INCLUDE, TWIN_INCLUDE], {"pair": _pair(), "twin": TWIN_OK}),
            f"Action name 'b1' is defined twice in {WF}: by branch 'pair' (branches/pair.yml) and by "
            "branch 'twin' (branches/twin.yml). Rename one of them.",
        ),
        (
            ([A, INCLUDE], {"pair": _pair(branch="pear")}),
            ([A, INCLUDE], {"pair": _pair(branch="pair")}),
            f"Branch 'pair' (branches/pair.yml), included in {WF}: the file has 'branch: pear'. The name must equal the file "
            "name 'pair'.",
        ),
        (
            ([A, INCLUDE], {"pair": _pair([B1, B2, {"include": "other"}])}),
            ([A, INCLUDE], {"pair": _pair([B1, B2])}),
            f"Branch 'pair' (branches/pair.yml), included in {WF}: the branch contains an include. A branch cannot include "
            "another branch.",
        ),
        (
            ([A, INCLUDE], {"pair": _pair(defaults={"run_mode": "batch"})}),
            ([A, INCLUDE], {"pair": _pair()}),
            f"Branch 'pair' (branches/pair.yml), included in {WF}: key 'defaults' is not a branch key. "
            "Branch keys: branch, description, inputs, outputs, actions.",
        ),
        (
            ([A, INCLUDE], {"pair": _pair([_with(B1, promt="x"), B2])}),
            ([A, INCLUDE], {"pair": _pair([B1, B2])}),
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': promt: Extra inputs are not permitted",
        ),
        (
            ([A, INCLUDE], {"pair": _pair([_with(B1, intent="first {{ x }}"), B2])}),
            ([A, INCLUDE], {"pair": _pair([_with(B1, intent="first x"), B2])}),
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': 'intent' holds Jinja. "
            "A branch file is plain YAML and is not rendered.",
        ),
        (
            ([A, INCLUDE], {"pair": _pair(outputs=["b3"])}),
            ([A, INCLUDE], {"pair": _pair(outputs=["b2"])}),
            f"Branch 'pair' (branches/pair.yml), included in {WF}: output 'b3' is not an action of the branch. "
            "Branch actions: b1, b2.",
        ),
        (
            ([A, INCLUDE], {"pair": _pair(inputs={"a": "Holds", "b1": "Holds"})}),
            ([A, INCLUDE], {"pair": _pair(inputs={"a": "Holds"})}),
            f"Branch 'pair' (branches/pair.yml), included in {WF}: 'b1' is declared as an input and defined as "
            "an action.",
        ),
    ],
    ids=[
        "later-key",
        "two-branches",
        "branch-name",
        "nested-include",
        "branch-key",
        "action-field",
        "jinja",
        "output",
        "input-named-like-action",
    ],
)
def test_a_refused_input_loads_once_its_fault_is_removed(tmp_path, bad, good, expected):
    assert _refusal(tmp_path / "bad", *bad) == expected
    assert _names(_render(tmp_path / "good", *good))[0] == "a"


def test_a_missing_branch_loads_once_its_file_exists():
    host = {"name": "wf", "description": "d", "actions": [copy.deepcopy(A), copy.deepcopy(INCLUDE)]}

    with pytest.raises(ConfigurationError) as caught:
        expand_workflow_includes(host, WF, {}, [])

    assert str(caught.value) == (
        f"Include 'pair' in {WF}: no branch file branches/pair.yml. Branch files found: none."
    )
    expanded, _ = expand_workflow_includes(host, WF, {"pair": _pair()}, ["pair"])
    assert [action["name"] for action in expanded["actions"]] == ["a", "b1", "b2"]


@pytest.fixture
def registry():
    before = dict(UDF_REGISTRY)
    yield UDF_REGISTRY
    UDF_REGISTRY.clear()
    UDF_REGISTRY.update(before)


def test_every_stamp_of_an_included_action_does_work_and_equals_inline(tmp_path, registry):
    tool = tmp_path / "pair_tools.py"
    tool.write_text(
        "from agent_actions import udf_tool\n\n\n"
        "@udf_tool()\ndef pair_two(data, **kwargs):\n    return {'text': 'x'}\n"
    )
    spec = importlib.util.spec_from_file_location("include_stamp_tools", tool)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    note = {
        "name": "b1",
        "kind": "llm",
        "intent": "first",
        "prompt": "$pair.Write_Note",
        "schema": "dispatch_task('pick_note')",
        "schema_options": ["note_a", "note_b"],
        "dependencies": ["a"],
        "context_scope": {"observe": ["a.text"]},
        "temperature": 0.2,
    }

    inline = _agents(tmp_path / "inline", [A, note, B2, C])
    included = _agents(tmp_path / "included", [A, INCLUDE, C], {"pair": _pair([note, B2])})

    stamps = {
        name: {key: compute(included[name]) for key, _, compute in _READS_STAMPS}
        for name in ("b1", "b2")
    }
    assert stamps["b1"]["schema_options_hash"] is not None
    assert stamps["b1"]["generation_hash"]
    assert stamps["b2"]["udf_source_hash"]
    for name in ("b1", "b2"):
        assert stamps[name] == {key: compute(inline[name]) for key, _, compute in _READS_STAMPS}
        assert _compute_action_config_hash(included[name]) == _compute_action_config_hash(
            inline[name]
        )


def _cli(tmp_path: Path, monkeypatch, actions, branches=None, branch_text: str | None = None):
    _project(tmp_path, actions, branches)
    (tmp_path / "agent_workflow" / "wf" / "agent_io" / "staging").mkdir(parents=True)
    if branch_text is not None:
        (tmp_path / "branches" / "pair.yml").write_text(branch_text)
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(cli, ["inspect", "-a", "wf"]).output.splitlines()


class TestTheCommandLineShowsTheRefusal:
    def test_an_invalid_branch_action_shows_the_branch_and_the_reason(self, tmp_path, monkeypatch):
        no_intent = {k: v for k, v in B1.items() if k != "intent"}

        lines = _cli(tmp_path, monkeypatch, [A, INCLUDE], {"pair": _pair([no_intent, B2])})

        assert (
            f"  Problem: Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': "
            "intent: Field required" in lines
        )
        assert "  Action: b1" in lines
        assert f"  File: {WF}" in lines

    def test_a_branch_file_that_is_not_yaml_shows_the_file_and_the_line(
        self, tmp_path, monkeypatch
    ):
        lines = _cli(tmp_path, monkeypatch, [A, INCLUDE], branch_text="branch: pair\nactions: [\n")

        assert (
            f"  Problem: Branch 'pair' (branches/pair.yml), included in {WF}: the file is not "
            "valid YAML (line 3, column 1): expected the node content, but found '<stream end>'."
        ) in lines
        assert f"  File: {WF}" in lines

    def test_a_branch_read_outside_the_branch_shows_the_workflow_file(self, tmp_path, monkeypatch):
        reader = _with(B2, dependencies=["b1", "z"])

        lines = _cli(tmp_path, monkeypatch, [A, Z, INCLUDE], {"pair": _pair([B1, reader])})

        assert f"  Problem: {_branch_reads_z('b2')}" in lines
        assert "  Action: b2" in lines
        assert f"  File: {WF}" in lines

    def test_a_written_origin_is_refused_on_the_command_line(self, tmp_path, monkeypatch):
        lines = _cli(tmp_path, monkeypatch, [_with(A, _include={"instance": "zz"}), INCLUDE])

        assert (
            f"  Problem: Action 'a' in {WF}: '_include' is set by the load on an included "
            "action and cannot be written in a workflow."
        ) in lines
        assert "  Action: a" in lines


class TestEveryBranchFileRefusalNamesBothFiles:
    def test_a_missing_required_key(self, tmp_path):
        no_description = {k: v for k, v in _pair().items() if k != "description"}

        message = _refusal(tmp_path / "bad", [A, INCLUDE], {"pair": no_description})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}: the file has no "
            "'description' key."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE])) == ["a", "b1", "b2"]

    def test_an_action_defined_twice(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, INCLUDE], {"pair": _pair([B1, B2, B1])})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': the branch "
            "defines this action twice."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE])) == ["a", "b1", "b2"]

    def test_a_prompt_that_is_not_a_template(self, tmp_path):
        reader = {
            "name": "b2",
            "kind": "llm",
            "intent": "second",
            "dependencies": ["b1"],
            "prompt": "$broken.Broken",
            "schema": {"note": "string"},
        }
        _project(tmp_path, [A, INCLUDE], {"pair": _pair([B1, reader])})
        (tmp_path / "prompt_store" / "broken.md").write_text(
            "{prompt Broken}\nSay {{ b1.text \n{end_prompt}\n"
        )

        with pytest.raises(ConfigurationError) as caught:
            render_pipeline_with_templates(
                tmp_path / WF, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
            )

        assert str(caught.value) == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b2': the prompt is "
            "not a valid template (line 1): unexpected end of template, expected 'end of print "
            "statement'."
        )


def _schema_judging(ref: str) -> dict:
    return {
        "fields": [{"id": "text", "type": "string"}],
        "expectations": [
            {
                "id": "grounded",
                "type": "llm_judge",
                "field": "text",
                "params": {"context": [ref], "rule": "ok"},
            }
        ],
    }


class TestAnExpectTheExpanderDropsIsNoRead:
    @pytest.mark.parametrize(
        "own, inherited",
        [({}, None), (None, {}), (None, {"repair": "auto"})],
        ids=["own-empty", "inherited-empty", "inherited-policy"],
    )
    def test_a_branch_tool_with_no_rule_of_its_own(self, tmp_path, own, inherited):
        reader = _with(B2, schema=_schema_judging("z.text"))
        if own is not None:
            reader["expect"] = own

        rendered = _with_defaults(
            tmp_path, [A, Z, INCLUDE], {"pair": _pair([B1, reader])}, inherited
        )

        assert _names(rendered) == ["a", "z", "b1", "b2"]

    def test_a_branch_tool_with_a_rule_still_reads_it(self, tmp_path):
        reader = _with(B2, schema=_schema_judging("z.text"), expect=_judged("z.text"))

        message = _refusal(tmp_path, [A, Z, INCLUDE], {"pair": _pair([B1, reader])})

        assert message == _branch_reads_z("b2")

    def test_a_host_tool_with_no_rule_of_its_own(self, tmp_path):
        reader = _with(C, schema=_schema_judging("b1.text"), expect={})

        assert _names(_render(tmp_path, [A, INCLUDE, reader])) == ["a", "b1", "b2", "c"]

    def test_a_host_tool_with_a_rule_still_reads_it(self, tmp_path):
        reader = _with(C, schema=_schema_judging("b1.text"), expect=_judged("b1.text"))

        message = _refusal(tmp_path, [A, INCLUDE, reader])

        assert message == (
            f"Action 'c' in {WF} reads 'b1', which branch 'pair' (branches/pair.yml) does not "
            "list under outputs. Outputs of 'pair': b2."
        )


class TestABranchWithNoOutputsSaysNone:
    def test_a_host_read(self, tmp_path):
        reader = _with(C, dependencies=["b2"])

        message = _refusal(tmp_path, [A, INCLUDE, reader], {"pair": _pair(outputs=[])})

        assert message == (
            f"Action 'c' in {WF} reads 'b2', which branch 'pair' (branches/pair.yml) does not "
            "list under outputs. Outputs of 'pair': none."
        )

    def test_a_binding(self, tmp_path):
        tail = _pair(
            [_with(B1, name="t1", impl="tail_one", dependencies=["b2"], context_scope={})],
            branch="tail",
            inputs={"b2": "Holds"},
            outputs=["t1"],
        )

        message = _refusal(
            tmp_path,
            [A, INCLUDE, {"include": "tail", "inputs": {"b2": "b2"}}],
            {"pair": _pair(outputs=[]), "tail": tail},
        )

        assert message == (
            f"Include 'tail' in {WF}: input 'b2' is bound to 'b2', which branch 'pair' "
            "(branches/pair.yml) does not list under outputs. Outputs of 'pair': none."
        )


NO_NAME = {k: v for k, v in C.items() if k != "name"}


class TestAMalformedActionGetsTheRefusalItGetsWithoutAnInclude:
    @pytest.mark.parametrize(
        "malformed",
        [NO_NAME, _with(C, dependencies=5)],
        ids=["no-name", "dependencies-not-a-list"],
    )
    def test_the_load_refuses_it_as_it_refuses_the_inline_workflow(self, tmp_path, malformed):
        with pytest.raises(ConfigurationError) as included:
            _agents(tmp_path / "included", [A, INCLUDE, malformed])
        with pytest.raises(ConfigurationError) as inline:
            _agents(tmp_path / "inline", [A, B1, B2, malformed])

        assert str(included.value) == "Workflow configuration is invalid"
        assert str(included.value) == str(inline.value)
        assert (
            included.value.context["validation_errors"] == inline.value.context["validation_errors"]
        )


class TestAWorkflowWithTwoDefectsGetsTheRefusalItGetsWithoutAnInclude:
    def test_a_bad_guard_and_a_wrong_workflow_name_give_the_inline_refusal(self, tmp_path):
        def refusal(root: Path, actions) -> str:
            workflow = _project(root, actions)
            data = yaml.safe_load(workflow.read_text())
            data["name"] = "other"
            workflow.write_text(yaml.safe_dump(data, sort_keys=False))
            with pytest.raises(ConfigurationError) as caught:
                manager = ConfigManager(
                    str(workflow), str(root / "agent_actions.yml"), project_root=root
                )
                manager.load_configs()
                manager.validate_agent_name()
                manager.get_user_agents()
            return f"{type(caught.value).__name__}: {caught.value}"

        bad_guard = _with(C, guard={"x": 1})

        included = refusal(tmp_path / "included", [A, INCLUDE, bad_guard])
        inline = refusal(tmp_path / "inline", [A, B1, B2, bad_guard])

        assert included == inline
        assert "guard" not in included


class TestTheWorkflowDefaultsWinOverTheProjectDefaults:
    def test_the_workflow_expect_replaces_the_project_expect(self, tmp_path):
        workflow = _project(tmp_path, [A, Z, INCLUDE])
        (tmp_path / "agent_actions.yml").write_text(
            "schema_path: schema\n"
            + yaml.safe_dump({"default_agent_config": {"expect": _judged("z.text")}})
        )
        data = yaml.safe_load(workflow.read_text())
        data["defaults"]["expect"] = _judged("a.text")
        workflow.write_text(yaml.safe_dump(data, sort_keys=False))

        rendered = yaml.safe_load(
            render_pipeline_with_templates(
                workflow, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
            )
        )

        assert _names(rendered) == ["a", "z", "b1", "b2"]
