"""An include entry overrides branch keys, removes branch actions and sets instance defaults."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml

from agent_actions.workflow.executor import _READS_STAMPS, _compute_action_config_hash
from tests.unit.cli.conftest import isolated_user_tools  # noqa: F401
from tests.unit.cli.test_inspect_shows_where_an_included_action_comes_from import TOOLS, _run
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    B1,
    B2,
    INCLUDE,
    WF,
    A,
    C,
    Z,
    _names,
    _pair,
    _project,
    _refusal,
    _render,
    _with,
)

OTHER_PROMPTS = """{prompt Rewrite_Note}
Rewrite the note about {{ a.text }} in one line.
{end_prompt}

{prompt Read_B1}
Check {{ b1.text }}.
{end_prompt}
"""
NOTE = {
    "name": "b1",
    "kind": "llm",
    "intent": "first",
    "prompt": "$pair.Write_Note",
    "schema": {"note": "string"},
    "dependencies": ["a"],
    "guard": {"condition": 'a.text != ""', "on_false": "filter"},
    "context_scope": {"observe": ["a.text"]},
}
B3 = {
    "name": "b3",
    "kind": "tool",
    "impl": "pair_three",
    "schema": {"text": "string"},
    "intent": "third",
    "dependencies": ["b1"],
    "context_scope": {"observe": ["b1.text"]},
}
WITH_Z = {"include": "pair", "inputs": {"a": "a", "z": "z"}}
BRANCH_PAIR = "branch 'pair' (branches/pair.yml)"


def _include(**keys) -> dict:
    return {**INCLUDE, **keys}


def _write(
    root: Path,
    actions,
    branches=None,
    workflow_defaults: dict | None = None,
    project_defaults: dict | None = None,
) -> Path:
    workflow = _project(root, actions, branches)
    (root / "prompt_store" / "other.md").write_text(OTHER_PROMPTS)
    if project_defaults is not None:
        project = yaml.safe_load((root / "agent_actions.yml").read_text())
        project["default_agent_config"] = project_defaults
        (root / "agent_actions.yml").write_text(yaml.safe_dump(project, sort_keys=False))
    if workflow_defaults is not None:
        data = yaml.safe_load(workflow.read_text())
        data["defaults"] = {**data["defaults"], **workflow_defaults}
        workflow.write_text(yaml.safe_dump(data, sort_keys=False))
    return workflow


def _rendered(root: Path, actions, branches=None, **defaults) -> dict:
    from agent_actions.prompt.render_workflow import render_pipeline_with_templates

    workflow = _write(root, actions, branches, **defaults)
    return yaml.safe_load(
        render_pipeline_with_templates(
            workflow, root / "templates", compile_schemas=False, project_root=root
        )
    )


def _loaded(root: Path, actions, branches=None, **defaults) -> dict[str, dict]:
    from agent_actions.config.manager import ConfigManager

    workflow = _write(root, actions, branches, **defaults)
    manager = ConfigManager(str(workflow), str(root / "agent_actions.yml"), project_root=root)
    manager.load_configs()
    manager.validate_agent_name()
    return {agent["name"]: agent for agent in manager.get_user_agents()}


def _by_name(rendered: dict) -> dict[str, dict]:
    return {action["name"]: action for action in rendered["actions"]}


def _without_origin(agent: dict) -> dict:
    return {key: value for key, value in agent.items() if key != "_include"}


class TestTheIncludeKeys:
    def test_as_is_refused_as_not_supported_yet(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(**{"as": "left"})])

        assert message == (
            f"Include 'pair' in {WF}: key 'as' is not supported yet. "
            "Include keys: include, inputs, defaults, override, remove."
        )

    def test_a_misspelt_key_names_the_nearest_include_key(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, _include(overide={"b1": {"intent": "x"}})])

        assert message == (
            f"Include 'pair' in {WF}: key 'overide' is not an include key. Did you mean "
            "'override'? Include keys: include, inputs, defaults, override, remove."
        )
        rendered = _render(tmp_path / "good", [A, _include(override={"b1": {"intent": "x"}})])
        assert _by_name(rendered)["b1"]["intent"] == "x"


class TestAnOverrideReplacesBranchKeys:
    def test_each_named_key_is_replaced_whole_and_the_rest_stay(self, tmp_path):
        override = {"b1": {"intent": "changed", "context_scope": {"observe": ["a.id"]}}}

        actions = _by_name(_render(tmp_path, [A, _include(override=override), C]))

        assert _without_origin(actions["b1"]) == {
            **B1,
            "intent": "changed",
            "context_scope": {"observe": ["a.id"]},
        }
        assert _without_origin(actions["b2"]) == B2
        assert actions["b1"]["_include"]["local_name"] == "b1"

    def test_null_removes_the_key(self, tmp_path):
        branch = _pair([_with(B1, record_limit=4), B2])

        actions = _by_name(
            _render(
                tmp_path,
                [A, _include(override={"b1": {"record_limit": None}})],
                {"pair": branch},
            )
        )

        assert "record_limit" not in actions["b1"]
        assert _without_origin(actions["b1"]) == B1

    @pytest.mark.parametrize("key", ["schema", "schema_name"])
    def test_either_spelling_of_the_schema_replaces_the_other(self, tmp_path, key):
        written = {"schema": "schema_name", "schema_name": "schema"}[key]
        named = {k: v for k, v in B1.items() if k != "schema"}
        branch = _pair(
            [{**named, written: "pair_text" if written == "schema_name" else {"a": "string"}}, B2]
        )
        value = {"line": "string"} if key == "schema" else "pair_line"

        actions = _by_name(
            _render(tmp_path, [A, _include(override={"b1": {key: value}})], {"pair": branch})
        )

        assert actions["b1"][key] == value
        assert written not in actions["b1"]

    def test_an_expect_block_is_replaced_and_not_merged(self, tmp_path):
        own = {"repair": "none", "expectations": [{"type": "not_null", "field": "text"}]}
        branch = _pair([_with(B1, expect=own), B2])
        replaced = {"expectations": [{"type": "not_null", "field": "id"}]}

        actions = _by_name(
            _render(
                tmp_path, [A, _include(override={"b1": {"expect": replaced}})], {"pair": branch}
            )
        )

        assert actions["b1"]["expect"] == replaced


class TestAnOverrideIsRefused:
    def test_an_action_the_branch_does_not_define(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, _include(override={"bb1": {"intent": "x"}})])

        assert message == (
            f"Include 'pair' in {WF}: override names 'bb1', which {BRANCH_PAIR} does not define. "
            "Did you mean 'b1'? Branch actions: b1, b2."
        )
        assert _names(_render(tmp_path / "good", [A, _include(override={"b1": {"intent": "x"}})]))

    def test_a_key_that_is_not_an_action_field(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, _include(override={"b1": {"intnt": "x"}})])

        assert message == (
            f"Include 'pair' in {WF}, override of 'b1' in {BRANCH_PAIR}: key 'intnt' is not an "
            "action field. Did you mean 'intent'?"
        )
        rendered = _render(tmp_path / "good", [A, _include(override={"b1": {"intent": "x"}})])
        assert _by_name(rendered)["b1"]["intent"] == "x"

    def test_the_name(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(override={"b1": {"name": "b9"}})])

        assert message == (
            f"Include 'pair' in {WF}, override of 'b1' in {BRANCH_PAIR}: key 'name' cannot be "
            "overridden. An included action keeps the name its branch gives it."
        )

    def test_a_value_that_makes_the_action_invalid_names_the_field(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, _include(override={"b1": {"record_limit": 0}})])

        assert message == (
            f"Include 'pair' in {WF}, override of 'b1' in {BRANCH_PAIR}: record_limit: "
            "Input should be greater than or equal to 1"
        )
        rendered = _render(tmp_path / "good", [A, _include(override={"b1": {"record_limit": 1}})])
        assert _by_name(rendered)["b1"]["record_limit"] == 1

    def test_null_on_a_required_key(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(override={"b1": {"intent": None}})])

        assert message == (
            f"Include 'pair' in {WF}, override of 'b1' in {BRANCH_PAIR}: intent: Field required"
        )

    def test_an_override_that_is_not_a_mapping_of_keys(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(override={"b1": ["intent"]})])

        assert message == (
            f"Include 'pair' in {WF}: 'override' must map each branch action to a mapping of "
            "action keys."
        )

    def test_an_action_named_under_both_override_and_remove(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(override={"b2": {"intent": "x"}}, remove=["b2"])])

        assert message == (
            f"Include 'pair' in {WF}: 'b2' of {BRANCH_PAIR} is named under both 'override' "
            "and 'remove'. Override it or remove it."
        )


class TestAnOverriddenReadIsCheckedAgain:
    @pytest.mark.parametrize(
        "override",
        [
            {"dependencies": ["b1", "z"]},
            {"context_scope": {"observe": ["b1.text", "z.text"]}},
            {"guard": {"condition": 'z.text != ""', "on_false": "filter"}},
            {"kind": "llm", "impl": None, "prompt": "$pair.Read_Z"},
        ],
        ids=["dependencies", "context_scope", "guard", "prompt"],
    )
    def test_a_read_outside_the_branch_through_an_override(self, tmp_path, override):
        message = _refusal(tmp_path / "bad", [A, Z, _include(override={"b2": override})])

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b2': reads 'z', "
            "which is not a branch action or a declared input. Declare it under 'inputs:'."
        )
        declared = _pair(inputs={"a": "Holds the text", "z": "Holds more"})
        rendered = _render(
            tmp_path / "good",
            [A, Z, {**WITH_Z, "override": {"b2": override}}],
            {"pair": declared},
        )
        assert _names(rendered) == ["a", "z", "b1", "b2"]

    def test_a_version_consumption_source_outside_the_branch(self, tmp_path):
        override = {"version_consumption": {"source": "z", "pattern": "merge"}}
        message = _refusal(tmp_path, [A, Z, _include(override={"b2": override})])

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b2': reads 'z', "
            "which is not a branch action or a declared input. Declare it under 'inputs:'."
        )


class TestRemoval:
    def test_a_removed_action_is_left_out(self, tmp_path):
        branch = _pair([B1, B2, B3], outputs=["b2"])

        rendered = _render(tmp_path, [A, _include(remove=["b3"]), C], {"pair": branch})

        assert _names(rendered) == ["a", "b1", "b2", "c"]

    def test_an_action_the_branch_does_not_define(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(remove=["bb2"])])

        assert message == (
            f"Include 'pair' in {WF}: remove names 'bb2', which {BRANCH_PAIR} does not define. "
            "Did you mean 'b2'? Branch actions: b1, b2."
        )

    def test_a_remove_that_is_not_a_list_of_names(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(remove="b2")])

        assert message == f"Include 'pair' in {WF}: 'remove' must be a list of branch action names."

    def test_a_reader_left_behind_is_named(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, _include(remove=["b1"])])

        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of {BRANCH_PAIR}, but 'b2' still reads "
            "it. Remove the readers too, or override them so that they do not read it."
        )
        rerouted = {"b2": {"dependencies": ["a"], "context_scope": {"observe": ["a.text"]}}}
        rendered = _render(tmp_path / "good", [A, _include(remove=["b1"], override=rerouted)])
        assert _names(rendered) == ["a", "b2"]

    def test_every_reader_is_named_and_a_versioned_reader_by_each_version(self, tmp_path):
        vote = _with(B3, name="vote", impl="pair_vote", versions={"range": [1, 2]})
        branch = _pair([B1, B2, vote], outputs=["b2"])

        message = _refusal(tmp_path, [A, _include(remove=["b1"])], {"pair": branch})

        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of {BRANCH_PAIR}, but 'b2', 'vote_1', "
            "'vote_2' still read it. Remove the readers too, or override them so that they do "
            "not read it."
        )

    def test_a_reader_through_the_prompt_alone(self, tmp_path):
        checker = {
            "name": "b2",
            "kind": "llm",
            "intent": "second",
            "dependencies": ["a"],
            "prompt": "$other.Read_B1",
            "schema": {"note": "string"},
        }
        branch = _pair([B1, checker])

        message = _refusal_of(tmp_path, [A, _include(remove=["b1"])], {"pair": branch})

        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of {BRANCH_PAIR}, but 'b2' still reads "
            "it. Remove the readers too, or override them so that they do not read it."
        )

    def test_a_removed_output_the_host_reads(self, tmp_path):
        branch = _pair([B1, B2, B3], outputs=["b2", "b3"])

        message = _refusal(tmp_path / "bad", [A, _include(remove=["b2"]), C], {"pair": branch})

        assert message == (
            f"Action 'c' in {WF} reads 'b2', which include 'pair' leaves out under 'remove:'. "
            f"Outputs that include 'pair' keeps from {BRANCH_PAIR}: b3."
        )
        rendered = _render(tmp_path / "good", [A, _include(remove=["b3"]), C], {"pair": branch})
        assert _names(rendered) == ["a", "b1", "b2", "c"]

    def test_a_removed_output_another_include_binds(self, tmp_path):
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

        message = _refusal(
            tmp_path,
            [A, _include(remove=["b2"]), {"include": "tail", "inputs": {"b2": "b2"}}],
            {"pair": _pair(), "tail": tail},
        )

        assert message == (
            f"Include 'tail' in {WF}: input 'b2' is bound to 'b2', which include 'pair' "
            "leaves out under 'remove:'."
        )


def _refusal_of(root: Path, actions, branches) -> str:
    from agent_actions.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as caught:
        _rendered(root, actions, branches)
    return str(caught.value)


class TestInstanceDefaults:
    def test_they_ride_on_the_origin_and_are_not_copied_onto_the_actions(self, tmp_path):
        actions = _by_name(_render(tmp_path, [A, _include(defaults={"record_limit": 1}), C]))

        assert actions["b1"]["_include"] == {
            "branch": "pair",
            "instance": "pair",
            "local_name": "b1",
            "branch_file": "branches/pair.yml",
            "defaults": {"record_limit": 1},
        }
        assert _without_origin(actions["b1"]) == B1
        assert "_include" not in actions["a"]

    def test_an_unknown_key_is_refused_as_in_workflow_defaults(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, _include(defaults={"record_limt": 1})])

        assert message.startswith(
            f"Include 'pair' in {WF}: defaults: Value error, unknown defaults key 'record_limt' "
            "— did you mean 'record_limit'?"
        )
        assert _names(_render(tmp_path / "good", [A, _include(defaults={"record_limit": 1})]))

    def test_a_bad_value_is_refused_as_in_workflow_defaults(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(defaults={"record_limit": 0})])

        assert message == (
            f"Include 'pair' in {WF}: defaults: record_limit: "
            "Input should be greater than or equal to 1"
        )

    def test_the_data_source_is_refused(self, tmp_path):
        source = {"type": "local", "folder": "./staging", "file_type": ["json"]}
        message = _refusal(tmp_path, [A, _include(defaults={"data_source": source})])

        assert message == (
            f"Include 'pair' in {WF}: defaults: 'data_source' is a setting of the workflow. "
            "Set it under the workflow's own 'defaults:'."
        )


LEVELS = ("project", "workflow", "instance", "action", "override")


@pytest.mark.parametrize(
    "written",
    [combo for size in range(len(LEVELS) + 1) for combo in itertools.combinations(LEVELS, size)],
    ids=lambda combo: "+".join(combo) or "none",
)
def test_the_most_specific_record_limit_wins(tmp_path, written):
    value = {level: index for index, level in enumerate(LEVELS, start=1)}
    include = _include(
        defaults={"record_limit": value["instance"]} if "instance" in written else None,
        override={"b1": {"record_limit": value["override"]}} if "override" in written else None,
    )
    include = {key: entry for key, entry in include.items() if entry is not None}
    branch = (
        _pair([_with(B1, record_limit=value["action"]), B2]) if "action" in written else _pair()
    )

    agents = _loaded(
        tmp_path,
        [A, include, C],
        {"pair": branch},
        workflow_defaults={"record_limit": value["workflow"]} if "workflow" in written else None,
        project_defaults={"record_limit": value["project"]} if "project" in written else None,
    )

    expected = max((value[level] for level in written), default=None)
    assert agents["b1"]["record_limit"] == expected
    outer = [level for level in written if level in ("project", "workflow", "instance")]
    assert agents["b2"]["record_limit"] == max((value[level] for level in outer), default=None)
    host = [level for level in written if level in ("project", "workflow")]
    assert agents["c"]["record_limit"] == max((value[level] for level in host), default=None)


@pytest.mark.parametrize("instance", [True, False], ids=["instance", "workflow"])
def test_an_override_of_null_falls_back_to_the_next_level(tmp_path, instance):
    include = _include(override={"b1": {"record_limit": None}})
    if instance:
        include["defaults"] = {"record_limit": 3}
    branch = _pair([_with(B1, record_limit=4), B2])

    agents = _loaded(
        tmp_path, [A, include], {"pair": branch}, workflow_defaults={"record_limit": 2}
    )

    assert agents["b1"]["record_limit"] == (3 if instance else 2)


class TestEachInheritedKeyFollowsTheExpanderRule:
    def test_the_seed_merges_through_every_level_and_survives_an_override(self, tmp_path):
        include = _include(
            defaults={"context_scope": {"seed": {"tone": "$file:tone.json"}}},
            override={"b1": {"context_scope": {"observe": ["a.id"]}}},
        )

        agents = _loaded(
            tmp_path,
            [A, include, C],
            workflow_defaults={"context_scope": {"seed": {"style": "$file:style.json"}}},
        )

        assert agents["b1"]["context_scope"] == {
            "seed": {"style": "$file:style.json", "tone": "$file:tone.json"},
            "observe": ["a.id"],
        }
        assert agents["b2"]["context_scope"] == {
            "seed": {"style": "$file:style.json", "tone": "$file:tone.json"},
            "observe": ["b1.text"],
        }
        assert agents["c"]["context_scope"] == {
            "seed": {"style": "$file:style.json"},
            "observe": ["b2.text"],
        }

    def test_a_batch_run_mode_reaches_the_llm_action_and_not_the_tool(self, tmp_path):
        agents = _loaded(
            tmp_path,
            [A, _include(defaults={"run_mode": "batch"}), C],
            {"pair": _pair([NOTE, B2])},
        )

        assert str(agents["b1"]["run_mode"].value) == "batch"
        assert str(agents["b2"]["run_mode"].value) == "online"
        assert str(agents["c"]["run_mode"].value) == "online"

    def test_a_file_granularity_reaches_the_tool_and_not_the_llm_action(self, tmp_path):
        agents = _loaded(
            tmp_path,
            [A, _include(defaults={"granularity": "file"}), C],
            {"pair": _pair([NOTE, B2])},
        )

        assert agents["b1"]["granularity"] == "Record"
        assert agents["b2"]["granularity"] == "File"
        assert agents["c"]["granularity"] == "Record"

    def test_an_expect_block_merges_key_by_key(self, tmp_path):
        rules = [{"type": "not_null", "field": "note"}]

        agents = _loaded(
            tmp_path,
            [A, _include(defaults={"expect": {"expectations": rules}}), C],
            {"pair": _pair([NOTE, B2])},
            workflow_defaults={"expect": {"judge_budget": 3}},
        )

        assert agents["b1"]["expect"]["judge_budget"] == 3
        assert agents["b1"]["expect"]["expectations"] == rules
        assert agents["c"]["expect"] is None

    def test_vendor_params_merge_key_by_key(self, tmp_path):
        agents = _loaded(
            tmp_path,
            [A, _include(defaults={"vendor_params": {"seed": 7}}), C],
            {"pair": _pair([NOTE, B2])},
            workflow_defaults={"vendor_params": {"user": "probe"}},
        )

        assert agents["b1"]["vendor_params"] == {"user": "probe", "seed": 7}
        assert agents["c"]["vendor_params"] == {"user": "probe"}

    def test_chunk_settings_merge_name_by_name_and_the_instance_wins(self, tmp_path):
        agents = _loaded(
            tmp_path,
            [A, _include(defaults={"chunk_size": 50, "chunk_overlap": 5}), C],
            {"pair": _pair([NOTE, B2])},
            workflow_defaults={"chunk_config": {"chunk_size": 100, "split_method": "chars"}},
        )

        assert agents["b1"]["chunk_config"] == {
            "chunk_size": 50,
            "chunk_overlap": 5,
            "split_method": "chars",
        }
        assert agents["c"]["chunk_config"] == {"chunk_size": 100, "split_method": "chars"}

    def test_an_inherited_judge_context_counts_as_a_branch_read(self, tmp_path):
        judged = {
            "expectations": [
                {
                    "type": "llm_judge",
                    "field": "note",
                    "params": {"context": ["z.text"], "criteria": "ok"},
                }
            ]
        }
        branch = _pair([NOTE, B2])

        message = _refusal_of(
            tmp_path / "bad", [A, Z, _include(defaults={"expect": judged})], {"pair": branch}
        )

        assert message == (
            f"Branch 'pair' (branches/pair.yml), included in {WF}, action 'b1': reads 'z', "
            "which is not a branch action or a declared input. Declare it under 'inputs:'."
        )
        declared = _pair([NOTE, B2], inputs={"a": "Holds the text", "z": "Holds more"})
        agents = _loaded(
            tmp_path / "good",
            [A, Z, {**WITH_Z, "defaults": {"expect": judged}}],
            {"pair": declared},
        )
        assert "z.text" in agents["b1"]["context_scope"]["observe"]
        assert "z.text" not in agents["a"]["context_scope"]["observe"]


class TestTheHashSeesTheFinalValueOnly:
    def test_an_override_hashes_as_the_same_value_written_inline(self, tmp_path):
        values = {
            "prompt": "$other.Rewrite_Note",
            "schema": {"line": "string"},
            "model_name": "gpt-4o",
            "guard": None,
        }
        inline_note = {key: value for key, value in {**NOTE, **values}.items() if value is not None}
        inline = _loaded(tmp_path / "inline", [A, inline_note, B2, C])
        overridden = _loaded(
            tmp_path / "overridden",
            [A, _include(override={"b1": values}), C],
            {"pair": _pair([NOTE, B2])},
        )
        plain = _loaded(tmp_path / "plain", [A, INCLUDE, C], {"pair": _pair([NOTE, B2])})

        assert _without_origin(overridden["b1"]) == inline["b1"]
        assert _compute_action_config_hash(overridden["b1"]) == _compute_action_config_hash(
            inline["b1"]
        )
        for key, _, compute in _READS_STAMPS:
            assert compute(overridden["b1"]) == compute(inline["b1"]), key
        assert _compute_action_config_hash(plain["b1"]) != _compute_action_config_hash(
            overridden["b1"]
        )

    def test_instance_defaults_hash_as_the_same_values_written_on_the_action(self, tmp_path):
        values = {"temperature": 0.7, "model_name": "gpt-4o"}
        inline = _loaded(tmp_path / "inline", [A, {**NOTE, **values}, B2, C])
        defaulted = _loaded(
            tmp_path / "defaulted",
            [A, _include(defaults=values), C],
            {"pair": _pair([NOTE, B2])},
        )

        assert defaulted["b1"]["_include"]["defaults"] == values
        assert _without_origin(defaulted["b1"]) == inline["b1"]
        assert _compute_action_config_hash(defaulted["b1"]) == _compute_action_config_hash(
            inline["b1"]
        )
        for key, _, compute in _READS_STAMPS:
            assert compute(defaulted["b1"]) == compute(inline["b1"]), key
        assert defaulted["b1"]["temperature"] == 0.7


@pytest.fixture
def project(tmp_path: Path, isolated_user_tools):  # noqa: F811
    def make(actions, branches=None) -> Path:
        root = tmp_path / "project"
        _write(root, actions, branches)
        (root / "tools").mkdir()
        (root / "tools" / "pair_tools.py").write_text(TOOLS)
        (root / "agent_workflow" / "wf" / "agent_io" / "staging").mkdir(parents=True)
        return root

    return make


class TestTheCommandLine:
    def test_inspect_shows_an_override_refusal_with_the_workflow_file(self, project, monkeypatch):
        root = project([A, _include(override={"bb1": {"intent": "x"}})])

        code, lines, _ = _run(root, monkeypatch, "-a", "wf")

        assert code != 0
        assert (
            f"  Problem: Include 'pair' in {WF}: override names 'bb1', which {BRANCH_PAIR} does "
            "not define. Did you mean 'b1'? Branch actions: b1, b2."
        ) in lines
        assert f"  File: {WF}" in lines

    def test_inspect_action_shows_the_values_the_instance_gives(self, project, monkeypatch):
        root = project([A, _include(defaults={"granularity": "file"}), C])

        code, included, _ = _run(root, monkeypatch, "action", "-a", "wf", "b1")
        _, host, _ = _run(root, monkeypatch, "action", "-a", "wf", "a")

        assert code == 0, "\n".join(included)
        assert "  Granularity  File" in included
        assert "  Granularity  Record" in host
