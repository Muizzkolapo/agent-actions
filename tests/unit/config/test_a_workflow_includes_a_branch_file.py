"""A workflow includes a shared branch file, which the load expands into ordinary actions."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.workflow.executor import _READS_STAMPS, _compute_action_config_hash

WF = "agent_workflow/wf/agent_config/wf.yml"

DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "OPENAI_API_KEY"}

PROMPTS = """{prompt Write_Note}
Write a note about {{ a.text }}.
{end_prompt}

{prompt Read_Z}
Compare {{ b1.text }} with {{ z.text }}.
{end_prompt}
"""

B1 = {
    "name": "b1",
    "kind": "tool",
    "impl": "pair_one",
    "schema": {"text": "string"},
    "intent": "first",
    "dependencies": ["a"],
    "context_scope": {"observe": ["a.text"]},
}
B2 = {
    "name": "b2",
    "kind": "tool",
    "impl": "pair_two",
    "schema": {"text": "string"},
    "intent": "second",
    "dependencies": ["b1"],
    "context_scope": {"observe": ["b1.text"]},
}
A = {
    "name": "a",
    "kind": "tool",
    "impl": "host_a",
    "schema": {"text": "string"},
    "intent": "host first",
    "context_scope": {"observe": ["source.text"]},
}
Z = {
    "name": "z",
    "kind": "tool",
    "impl": "host_z",
    "schema": {"text": "string"},
    "intent": "host side",
    "dependencies": ["a"],
    "context_scope": {"observe": ["a.text"]},
}
C = {
    "name": "c",
    "kind": "tool",
    "impl": "host_c",
    "schema": {"text": "string"},
    "intent": "host last",
    "dependencies": ["b2"],
    "context_scope": {"observe": ["b2.text"]},
}
INCLUDE = {"include": "pair", "inputs": {"a": "a"}}


def _pair(actions=None, **over):
    branch = {
        "branch": "pair",
        "description": "Two tool actions",
        "inputs": {"a": "Holds the text"},
        "outputs": ["b2"],
        "actions": copy.deepcopy(actions if actions is not None else [B1, B2]),
    }
    branch.update(over)
    return branch


def _project(tmp_path: Path, actions, branches=None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\ntool_path: [tools]\n")
    (tmp_path / "schema").mkdir(exist_ok=True)
    (tmp_path / "prompt_store").mkdir(exist_ok=True)
    (tmp_path / "prompt_store" / "pair.md").write_text(PROMPTS)
    folder = tmp_path / "branches"
    folder.mkdir(exist_ok=True)
    for name, body in (branches if branches is not None else {"pair": _pair()}).items():
        (folder / f"{name}.yml").write_text(yaml.safe_dump(body, sort_keys=False))
    workflow = tmp_path / WF
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        yaml.safe_dump(
            {
                "name": "wf",
                "description": "d",
                "defaults": DEFAULTS,
                "actions": copy.deepcopy(actions),
            },
            sort_keys=False,
        )
    )
    return workflow


def _render(tmp_path: Path, actions, branches=None) -> dict:
    workflow = _project(tmp_path, actions, branches)
    return yaml.safe_load(
        render_pipeline_with_templates(
            workflow, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
        )
    )


def _refusal(tmp_path: Path, actions, branches=None) -> str:
    with pytest.raises(ConfigurationError) as caught:
        _render(tmp_path, actions, branches)
    return str(caught.value)


def _agents(root: Path, actions, branches=None) -> dict[str, dict]:
    workflow = _project(root, actions, branches)
    manager = ConfigManager(str(workflow), str(root / "agent_actions.yml"), project_root=root)
    manager.load_configs()
    manager.validate_agent_name()
    return {agent["name"]: agent for agent in manager.get_user_agents()}


def _names(rendered: dict) -> list[str]:
    return [action.get("name") for action in rendered["actions"]]


def _with(action: dict, **over) -> dict:
    return {**copy.deepcopy(action), **over}


class TestTheIncludeExpands:
    def test_branch_actions_take_the_place_of_the_include_in_branch_order(self, tmp_path):
        rendered = _render(tmp_path, [A, INCLUDE, C])

        assert _names(rendered) == ["a", "b1", "b2", "c"]

    def test_each_included_action_carries_its_origin_and_no_host_action_does(self, tmp_path):
        rendered = _render(tmp_path, [A, INCLUDE, C])
        assert _names(rendered) == ["a", "b1", "b2", "c"]
        actions = {action["name"]: action for action in rendered["actions"]}

        for local in ("b1", "b2"):
            assert actions[local]["_include"] == {
                "branch": "pair",
                "instance": "pair",
                "local_name": local,
                "branch_file": "branches/pair.yml",
            }
        assert "_include" not in actions["a"]
        assert "_include" not in actions["c"]

    def test_an_included_action_equals_the_same_action_written_inline(self, tmp_path):
        rendered = _render(tmp_path, [A, INCLUDE, C])
        assert _names(rendered) == ["a", "b1", "b2", "c"]
        actions = {action["name"]: action for action in rendered["actions"]}

        for local, written in (("b1", B1), ("b2", B2)):
            without_origin = {k: v for k, v in actions[local].items() if k != "_include"}
            assert without_origin == written

    def test_versions_in_a_branch_expand_after_the_include(self, tmp_path):
        vote = {
            "name": "vote",
            "kind": "tool",
            "impl": "pair_vote",
            "intent": "vote",
            "dependencies": ["a"],
            "versions": {"range": [1, 2]},
            "context_scope": {"observe": ["a.text"]},
        }
        tally = {
            "name": "tally",
            "kind": "tool",
            "impl": "host_tally",
            "intent": "tally",
            "dependencies": ["vote"],
            "version_consumption": {"source": "vote", "pattern": "merge"},
            "context_scope": {"observe": ["vote.text"]},
        }
        rendered = _render(
            tmp_path, [A, INCLUDE, tally], {"pair": _pair([vote], outputs=["vote"])}
        )
        assert _names(rendered) == ["a", "vote_1", "vote_2", "tally"]
        actions = {action["name"]: action for action in rendered["actions"]}
        assert actions["vote_2"]["_include"]["local_name"] == "vote"
        assert actions["vote_2"]["_version_context"]["base_name"] == "vote"

    def test_a_branch_reads_the_output_of_another_branch_through_an_input(self, tmp_path):
        tail = {
            "branch": "tail",
            "description": "Reads the pair",
            "inputs": {"b2": "Holds the second text"},
            "outputs": ["t1"],
            "actions": [
                {
                    "name": "t1",
                    "kind": "tool",
                    "impl": "tail_one",
                    "intent": "tail",
                    "dependencies": ["b2"],
                    "context_scope": {"observe": ["b2.text"]},
                }
            ],
        }
        rendered = _render(
            tmp_path,
            [A, INCLUDE, {"include": "tail", "inputs": {"b2": "b2"}}],
            {"pair": _pair(), "tail": tail},
        )

        assert _names(rendered) == ["a", "b1", "b2", "t1"]


class TestTheLoadedWorkflowIsAnOrdinaryWorkflow:
    def test_config_manager_hands_out_the_included_actions_with_their_origin(self, tmp_path):
        agents = _agents(tmp_path, [A, INCLUDE, C])

        assert list(agents) == ["a", "b1", "b2", "c"]
        assert agents["b1"]["_include"]["branch"] == "pair"
        assert "_include" not in agents["a"]

    def test_the_stamps_of_an_included_action_equal_those_written_inline(self, tmp_path):
        note = {
            "name": "b1",
            "kind": "llm",
            "intent": "first",
            "prompt": "$pair.Write_Note",
            "schema": {"note": "string"},
            "dependencies": ["a"],
            "guard": {"condition": 'a.text != ""', "on_false": "filter"},
            "context_scope": {"observe": ["a.text"]},
            "temperature": 0.2,
        }
        inline = _agents(tmp_path / "inline", [A, note, B2, C])
        included = _agents(tmp_path / "included", [A, INCLUDE, C], {"pair": _pair([note, B2])})

        for name in ("b1", "b2"):
            assert "_include" in included[name]
            assert "_include" not in inline[name]
            assert _compute_action_config_hash(included[name]) == _compute_action_config_hash(
                inline[name]
            )
            for key, _, compute in _READS_STAMPS:
                assert compute(included[name]) == compute(inline[name]), key

    def test_a_cycle_through_a_branch_names_the_origin_of_each_branch_action(self, tmp_path):
        looped = _with(A, dependencies=["b2"], context_scope={"observe": ["b2.text"]})

        with pytest.raises(ConfigurationError) as caught:
            _agents(tmp_path / "looped", [looped, INCLUDE])
        messages = [error["message"] for error in caught.value.context["validation_errors"]]

        assert messages == [
            "Value error, Circular dependency detected: a -> b2 -> b1 -> a. "
            "'b2', 'b1' come from branch 'pair' (branches/pair.yml)."
        ]
        assert list(_agents(tmp_path / "open", [A, INCLUDE])) == ["a", "b1", "b2"]


class TestTheIncludeEntryIsRefused:
    def test_a_missing_branch_file_lists_the_branch_files(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, {"include": "pairr", "inputs": {"a": "a"}}])

        assert message == (
            f"Include 'pairr' in {WF}: no branch file branches/pairr.yml. Branch files "
            "found: pair."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE])) == ["a", "b1", "b2"]

    @pytest.mark.parametrize(
        "key, expected",
        [
            ("input", "key 'input' is not an include key. Did you mean 'inputs'?"),
            ("zzz", "key 'zzz' is not an include key."),
        ],
    )
    def test_an_unknown_include_key_lists_the_include_keys(self, tmp_path, key, expected):
        message = _refusal(tmp_path / "bad", [A, {**INCLUDE, key: {"a": "a"}}])

        assert message == (
            f"Include 'pair' in {WF}: {expected} "
            "Include keys: include, as, inputs, defaults, override, remove."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE])) == ["a", "b1", "b2"]

    def test_an_unbound_input_is_refused(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, {"include": "pair"}])

        assert message == (
            f"Include 'pair' in {WF}: input 'a' of branch 'pair' (branches/pair.yml) is "
            "not bound. "
            "Bind it under 'inputs:' to an action of workflow 'wf'."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE])) == ["a", "b1", "b2"]

    def test_a_renaming_binding_is_refused(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, Z, {"include": "pair", "inputs": {"a": "z"}}])

        assert message == (
            f"Include 'pair' in {WF}: input 'a' is bound to 'z'. A branch reads an input by "
            "its own name, so 'a' must be bound to an action named 'a'."
        )
        assert _names(_render(tmp_path / "good", [A, Z, INCLUDE])) == ["a", "z", "b1", "b2"]

    def test_a_binding_to_a_missing_action_is_refused(self, tmp_path):
        message = _refusal(tmp_path / "bad", [Z, INCLUDE])

        assert message == (
            f"Include 'pair' in {WF}: input 'a' is bound to 'a', "
            "which is not an action of workflow 'wf'."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE])) == ["a", "b1", "b2"]

    def test_a_binding_of_an_input_the_branch_does_not_declare_is_refused(self, tmp_path):
        message = _refusal(
            tmp_path / "bad", [A, Z, {"include": "pair", "inputs": {"a": "a", "z": "z"}}]
        )

        assert message == (
            f"Include 'pair' in {WF}: 'inputs' names 'z', which branch 'pair' (branches/pair.yml) "
            "does not declare. Branch inputs: a."
        )
        assert _names(_render(tmp_path / "good", [A, Z, INCLUDE])) == ["a", "z", "b1", "b2"]

    def test_a_binding_to_an_action_another_branch_keeps_internal_is_refused(self, tmp_path):
        def tail(read):
            return {
                "branch": "tail",
                "description": "Reads the pair",
                "inputs": {read: "Holds a text"},
                "outputs": ["t1"],
                "actions": [
                    {
                        "name": "t1",
                        "kind": "tool",
                        "impl": "tail_one",
                        "intent": "tail",
                        "dependencies": [read],
                        "context_scope": {"observe": [f"{read}.text"]},
                    }
                ],
            }

        message = _refusal(
            tmp_path / "bad",
            [A, INCLUDE, {"include": "tail", "inputs": {"b1": "b1"}}],
            {"pair": _pair(), "tail": tail("b1")},
        )

        assert message == (
            f"Include 'tail' in {WF}: input 'b1' is bound to 'b1', which branch 'pair' "
            "(branches/pair.yml) does not list under outputs. Outputs of 'pair': b2."
        )
        rendered = _render(
            tmp_path / "good",
            [A, INCLUDE, {"include": "tail", "inputs": {"b2": "b2"}}],
            {"pair": _pair(), "tail": tail("b2")},
        )
        assert _names(rendered) == ["a", "b1", "b2", "t1"]

    def test_one_branch_included_twice_is_refused(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, INCLUDE, INCLUDE])

        assert message == (
            f"Workflow 'wf' ({WF}) includes branch 'pair' (branches/pair.yml) twice with "
            "the instance name "
            "'pair'. Give each include its own instance name with 'as:'."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE])) == ["a", "b1", "b2"]


class TestANameCollisionIsRefusedWithBothOrigins:
    def test_a_host_action_with_the_name_of_a_branch_action(self, tmp_path):
        clash = _with(Z, name="b1")
        message = _refusal(tmp_path / "bad", [A, clash, INCLUDE])

        assert message == (
            f"Action name 'b1' is defined twice in {WF}: by workflow 'wf' and by branch "
            "'pair' (branches/pair.yml). Rename one of them."
        )
        assert _names(_render(tmp_path / "good", [A, Z, INCLUDE])) == ["a", "z", "b1", "b2"]

    def test_a_host_version_with_the_name_of_a_branch_action(self, tmp_path):
        versioned = _with(Z, name="b", versions={"range": [1, 2]})
        message = _refusal(
            tmp_path / "bad",
            [A, versioned, INCLUDE],
            {
                "pair": _pair(
                    [
                        _with(B1, name="b_2"),
                        _with(B2, dependencies=["b_2"], context_scope={"observe": ["b_2.text"]}),
                    ]
                )
            },
        )

        assert message == (
            f"Action name 'b_2' is defined twice in {WF}: by workflow 'wf' and by branch "
            "'pair' (branches/pair.yml). Rename one of them."
        )
        rendered = _render(tmp_path / "good", [A, versioned, INCLUDE])
        assert _names(rendered) == ["a", "b_1", "b_2", "b1", "b2"]

    def test_two_branches_that_define_one_name(self, tmp_path):
        twin = _pair(branch="twin", outputs=[])
        twin["actions"] = [_with(B1, impl="twin_one")]
        message = _refusal(
            tmp_path,
            [A, INCLUDE, {"include": "twin", "inputs": {"a": "a"}}],
            {"pair": _pair(), "twin": twin},
        )

        assert message == (
            f"Action name 'b1' is defined twice in {WF}: by branch 'pair' "
            "(branches/pair.yml) and by "
            "branch 'twin' (branches/twin.yml). Rename one of them."
        )


class TestTheHostReadsOnlyDeclaredOutputs:
    @pytest.mark.parametrize(
        "reader",
        [
            _with(C, dependencies=["b1"], context_scope={"observe": ["b1.text"]}),
            _with(C, context_scope={"observe": ["b2.text", "b1.text"]}),
            _with(C, guard={"condition": 'b1.text != ""', "on_false": "filter"}),
            {
                "name": "c",
                "kind": "llm",
                "intent": "host last",
                "dependencies": ["b2"],
                "prompt": "Summarize {{ b1.text }}.",
                "schema": {"note": "string"},
            },
        ],
        ids=["dependencies", "context_scope", "guard", "prompt"],
    )
    def test_a_host_read_of_a_branch_internal_is_refused(self, tmp_path, reader):
        message = _refusal(tmp_path / "bad", [A, INCLUDE, reader])

        assert message == (
            f"Action 'c' in {WF} reads 'b1', which branch 'pair' (branches/pair.yml) does "
            "not list under "
            "outputs. Outputs of 'pair': b2."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE, C])) == ["a", "b1", "b2", "c"]


class TestABranchReadsOnlyItsOwnActionsAndInputs:
    @pytest.mark.parametrize(
        "reader",
        [
            _with(B2, dependencies=["b1", "z"]),
            _with(B2, context_scope={"observe": ["b1.text", "z.text"]}),
            _with(B2, guard={"condition": 'z.text != ""', "on_false": "filter"}),
            {
                "name": "b2",
                "kind": "llm",
                "intent": "second",
                "dependencies": ["b1"],
                "prompt": "$pair.Read_Z",
                "schema": {"note": "string"},
            },
        ],
        ids=["dependencies", "context_scope", "guard", "prompt"],
    )
    def test_a_read_outside_the_branch_is_refused(self, tmp_path, reader):
        message = _refusal(tmp_path / "bad", [A, Z, INCLUDE], {"pair": _pair([B1, reader])})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b2': reads "
            "'z', which is not a "
            "branch action or a declared input. Declare it under 'inputs:'."
        )
        declared = _pair([B1, reader], inputs={"a": "Holds the text", "z": "Holds more"})
        rendered = _render(
            tmp_path / "good",
            [A, Z, {"include": "pair", "inputs": {"a": "a", "z": "z"}}],
            {"pair": declared},
        )
        assert _names(rendered) == ["a", "z", "b1", "b2"]


class TestTheBranchFileIsRefused:
    def test_a_branch_name_that_differs_from_the_file_name(self, tmp_path):
        message = _refusal(tmp_path, [A, INCLUDE], {"pair": _pair(branch="pear")})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}: the file has 'branch: pear'. "
            "The name must equal the file name 'pair'."
        )

    def test_an_include_inside_a_branch(self, tmp_path):
        nested = _pair([B1, B2, {"include": "other"}])
        message = _refusal(tmp_path, [A, INCLUDE], {"pair": nested})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}: the branch contains an "
            "include. "
            "A branch cannot include another branch."
        )

    @pytest.mark.parametrize(
        "name, reason",
        [
            ("b__1", "contains '__', which is reserved for instance names."),
            ("b1_", "ends with '_'."),
            ("1b", "does not start with a letter."),
            ("b-1", "holds a character that is not a letter, a digit or '_'."),
        ],
    )
    def test_an_action_name_that_cannot_take_a_prefix(self, tmp_path, name, reason):
        renamed = _pair(
            [
                _with(B1, name=name),
                _with(B2, dependencies=[name], context_scope={"observe": [f"{name}.text"]}),
            ]
        )
        message = _refusal(tmp_path / "bad", [A, INCLUDE], {"pair": renamed})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action '{name}': the "
            f"name {reason} "
            "Use letters, digits and single underscores, starting with a letter."
        )
        assert _names(_render(tmp_path / "good", [A, INCLUDE])) == ["a", "b1", "b2"]

    def test_a_key_that_is_not_a_branch_key(self, tmp_path):
        message = _refusal(tmp_path, [A, INCLUDE], {"pair": _pair(defaults={"run_mode": "batch"})})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}: key 'defaults' is not "
            "a branch key. "
            "Branch keys: branch, description, inputs, outputs, actions."
        )

    def test_an_action_that_is_not_a_valid_action(self, tmp_path):
        message = _refusal(tmp_path, [A, INCLUDE], {"pair": _pair([_with(B1, promt="x"), B2])})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': promt: "
            "Extra inputs are not permitted"
        )

    def test_an_inline_prompt(self, tmp_path):
        inline = {
            "name": "b1",
            "kind": "llm",
            "intent": "first",
            "dependencies": ["a"],
            "prompt": "Write a note about {{ a.text }}.",
            "schema": {"note": "string"},
        }
        message = _refusal(tmp_path / "bad", [A, INCLUDE], {"pair": _pair([inline, B2])})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': the "
            "prompt is written inline. "
            "A branch action names a prompt store block, for example 'prompt: $store.Block'."
        )
        stored = _pair([_with(inline, prompt="$pair.Write_Note"), B2])
        assert _names(_render(tmp_path / "good", [A, INCLUDE], {"pair": stored})) == [
            "a",
            "b1",
            "b2",
        ]

    def test_jinja_in_a_value(self, tmp_path):
        message = _refusal(
            tmp_path, [A, INCLUDE], {"pair": _pair([_with(B1, intent="first {{ x }}"), B2])}
        )

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': 'intent' "
            "holds Jinja. "
            "A branch file is plain YAML and is not rendered."
        )

    def test_an_output_that_is_not_a_branch_action(self, tmp_path):
        message = _refusal(tmp_path, [A, INCLUDE], {"pair": _pair(outputs=["b3"])})

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}: output 'b3' is not an "
            "action of the branch. "
            "Branch actions: b1, b2."
        )

    def test_an_input_with_the_name_of_a_branch_action(self, tmp_path):
        message = _refusal(
            tmp_path, [A, INCLUDE], {"pair": _pair(inputs={"a": "Holds", "b1": "Holds"})}
        )

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}: 'b1' is declared as an input "
            "and defined as an action."
        )


class TestAWorkflowWithoutAnIncludeIsUnchanged:
    def test_it_renders_without_origin(self, tmp_path):
        rendered = _render(tmp_path, [A, Z])

        assert _names(rendered) == ["a", "z"]
        assert all("_include" not in action for action in rendered["actions"])
