"""What an included action inherits from the defaults is held to the branch boundary."""

from __future__ import annotations

import json

import pytest

from agent_actions.prompt.renderer import ConfigRenderingService
from agent_actions.tooling.docs.parser import WorkflowParser
from tests.unit.cli.conftest import isolated_user_tools  # noqa: F401
from tests.unit.cli.test_inspect_shows_where_an_included_action_comes_from import TOOLS, _run
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
)
from tests.unit.config.test_an_include_overrides_removes_and_sets_defaults import (
    NOTE,
    WITH_Z,
    _include,
    _loaded,
    _rendered,
    _write,
)

DIRECTIVES = ["observe", "passthrough", "drop"]
DECLARING_Z = {"inputs": {"a": "Holds the text", "z": "Holds more"}}
TAIL = {
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


def _refusal_of(root, actions, branches, **defaults) -> str:
    from agent_actions.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as caught:
        _rendered(root, actions, branches, **defaults)
    return str(caught.value)


def _judged(ref: str) -> dict:
    return {
        "expectations": [
            {"type": "llm_judge", "field": "note", "params": {"context": [ref], "criteria": "ok"}}
        ]
    }


def _branch_reads(
    name: str, read: str, level: str = "", branch: str = "pair", key: str = "context_scope"
) -> str:
    via = f" (from '{key}' under {level})" if level else ""
    return (
        f"Branch '{branch}' (branches/{branch}.yml), included in {WF}, action '{name}': reads "
        f"'{read}'{via}, which is not a branch action or a declared input. Declare it under "
        "'inputs:'."
    )


class TestAnInheritedContextScopeIsABranchRead:
    @pytest.mark.parametrize("directive", DIRECTIVES)
    def test_from_the_include_defaults(self, tmp_path, directive):
        scope = {"context_scope": {directive: ["z.text"]}}

        message = _refusal(tmp_path / "bad", [A, Z, _include(defaults=scope)])

        assert message == _branch_reads("b1", "z", "'defaults:' of include 'pair'")
        agents = _loaded(
            tmp_path / "good",
            [A, Z, {**WITH_Z, "defaults": scope}],
            {"pair": _pair(**DECLARING_Z)},
        )
        assert "z.text" in agents["b1"]["context_scope"][directive]
        assert "z.text" not in agents["a"]["context_scope"].get(directive, [])

    @pytest.mark.parametrize("directive", DIRECTIVES)
    def test_from_the_workflow_defaults(self, tmp_path, directive):
        scope = {"context_scope": {directive: ["z.text"]}}

        message = _refusal_of(tmp_path / "bad", [A, Z, INCLUDE], None, workflow_defaults=scope)

        assert message == _branch_reads("b1", "z", "the workflow's 'defaults:'")
        agents = _loaded(
            tmp_path / "good",
            [A, Z, WITH_Z],
            {"pair": _pair(**DECLARING_Z)},
            workflow_defaults=scope,
        )
        assert "z.text" in agents["b1"]["context_scope"][directive]

    def test_from_the_project_defaults(self, tmp_path):
        scope = {"context_scope": {"observe": ["z.text"]}}

        message = _refusal_of(tmp_path / "bad", [A, Z, INCLUDE], None, project_defaults=scope)

        assert message == _branch_reads("b1", "z", "'default_agent_config:' in agent_actions.yml")
        rendered = _rendered(
            tmp_path / "good",
            [A, Z, WITH_Z],
            {"pair": _pair(**DECLARING_Z)},
            project_defaults=scope,
        )
        assert _names(rendered) == ["a", "z", "b1", "b2"]

    def test_from_the_include_defaults_into_another_branch(self, tmp_path):
        def tail_include(read: str) -> dict:
            return {
                "include": "tail",
                "inputs": {"b2": "b2"},
                "defaults": {"context_scope": {"observe": [f"{read}.text"]}},
            }

        message = _refusal(
            tmp_path / "bad", [A, INCLUDE, tail_include("b1")], {"pair": _pair(), "tail": TAIL}
        )

        assert message == _branch_reads("t1", "b1", "'defaults:' of include 'tail'", "tail")
        rendered = _render(
            tmp_path / "good", [A, INCLUDE, tail_include("b2")], {"pair": _pair(), "tail": TAIL}
        )
        assert _names(rendered) == ["a", "b1", "b2", "t1"]

    def test_an_own_read_keeps_the_plain_refusal(self, tmp_path):
        override = {"b2": {"context_scope": {"observe": ["b1.text", "z.text"]}}}
        scope = {"context_scope": {"observe": ["z.text"]}}

        message = _refusal(tmp_path, [A, Z, _include(override=override, defaults=scope)])

        assert message == _branch_reads("b1", "z", "'defaults:' of include 'pair'")
        own = _refusal(tmp_path / "own", [A, Z, _include(override=override)])
        assert own == _branch_reads("b2", "z")

    def test_a_seed_is_not_an_action_read(self, tmp_path):
        include = _include(defaults={"context_scope": {"seed": {"z": "$file:z.json"}}})

        agents = _loaded(
            tmp_path,
            [A, Z, include],
            workflow_defaults={"context_scope": {"seed": {"a": "$file:a.json"}}},
        )

        assert agents["b1"]["context_scope"]["seed"] == {"a": "$file:a.json", "z": "$file:z.json"}


class TestAHostReadThroughTheWorkflowDefaults:
    @pytest.mark.parametrize("directive", DIRECTIVES)
    def test_of_a_branch_internal_is_refused(self, tmp_path, directive):
        def scope(read: str) -> dict:
            return {"context_scope": {directive: [f"{read}.text"]}}

        message = _refusal_of(tmp_path / "bad", [A, INCLUDE], None, workflow_defaults=scope("b1"))

        assert message == (
            f"Action 'a' in {WF} reads 'b1' (from 'context_scope' under the workflow's "
            "'defaults:'), which branch 'pair' (branches/pair.yml) does not list under outputs. "
            "Outputs of 'pair': b2."
        )
        rendered = _rendered(tmp_path / "good", [A, INCLUDE], None, workflow_defaults=scope("b2"))
        assert _names(rendered) == ["a", "b1", "b2"]

    def test_a_workflow_with_no_include_is_unchanged(self, tmp_path):
        scope = {"context_scope": {"observe": ["z.text"]}}

        rendered = _rendered(tmp_path, [A, Z], None, workflow_defaults=scope)
        agents = _loaded(tmp_path / "loaded", [A, Z], None, workflow_defaults=scope)

        assert _names(rendered) == ["a", "z"]
        assert agents["a"]["context_scope"]["observe"] == ["z.text", "source.text"]


class TestAnInheritedReadOfARemovedAction:
    REROUTED = {"b2": {"dependencies": ["a"], "context_scope": {"observe": ["a.text"]}}}

    def test_through_the_include_context_scope(self, tmp_path):
        include = _include(
            remove=["b1"],
            override=self.REROUTED,
            defaults={"context_scope": {"observe": ["b1.text"]}},
        )

        message = _refusal(tmp_path / "bad", [A, include])

        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of branch 'pair' (branches/pair.yml), but "
            "'b2' (from 'context_scope' under 'defaults:' of include 'pair') still reads it. "
            "Remove the readers too, override them so that they do not read it, or remove the read "
            "from the defaults named above. In an override, null takes away an inherited directive, "
            "and a list is added to it."
        )
        rendered = _render(tmp_path / "good", [A, _include(remove=["b1"], override=self.REROUTED)])
        assert _names(rendered) == ["a", "b2"]

    def test_through_the_include_expect(self, tmp_path):
        b3 = {
            **{k: v for k, v in NOTE.items() if k != "guard"},
            "name": "b3",
            "dependencies": ["b2"],
            "context_scope": {"observe": ["b2.text"]},
        }
        include = _include(
            remove=["b1"], override=self.REROUTED, defaults={"expect": _judged("b1.text")}
        )

        message = _refusal_of(tmp_path, [A, include], {"pair": _pair([B1, B2, b3], outputs=["b3"])})

        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of branch 'pair' (branches/pair.yml), but "
            "'b2' (from 'expect' under 'defaults:' of include 'pair'), 'b3' (from 'expect' under "
            "'defaults:' of include 'pair') still read it. Remove the readers too, override them "
            "so that they do not read it, or remove the read from the defaults named above. In an "
            "override, null takes away an inherited directive, and a list is added to it."
        )


class TestTheIncludeLevelWinsInTheReadCheck:
    def test_an_include_expect_replaces_the_workflow_judge(self, tmp_path):
        plain = {"expectations": [{"type": "not_null", "field": "note"}]}

        agents = _loaded(
            tmp_path / "replaced",
            [A, Z, _include(defaults={"expect": plain})],
            {"pair": _pair([NOTE, B2])},
            workflow_defaults={"expect": _judged("z.text")},
        )
        message = _refusal_of(
            tmp_path / "workflow",
            [A, Z, INCLUDE],
            {"pair": _pair([NOTE, B2])},
            workflow_defaults={"expect": _judged("z.text")},
        )

        assert agents["b1"]["expect"]["expectations"] == plain["expectations"]
        assert "z.text" not in agents["b1"]["context_scope"]["observe"]
        assert message == _branch_reads("b1", "z", "the workflow's 'defaults:'", key="expect")

    def test_nested_chunk_config_beats_the_flat_setting_inside_the_include_level(self, tmp_path):
        chunk = {"chunk_size": 70, "chunk_config": {"chunk_size": 50}}

        agents = _loaded(tmp_path, [A, _include(defaults=chunk)], {"pair": _pair([NOTE, B2])})
        inline = _loaded(tmp_path / "inline", [A, {**NOTE, **chunk}, B2])

        assert agents["b1"]["chunk_config"]["chunk_size"] == 50
        assert agents["b1"]["chunk_config"] == inline["b1"]["chunk_config"]


class TestTheIncludeDefaultsAreRefusedInFull:
    def test_an_unknown_key(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, _include(defaults={"record_limt": 1})])

        assert message == (
            f"Include 'pair' in {WF}: defaults: Value error, unknown defaults key 'record_limt' "
            "— did you mean 'record_limit'?; valid defaults keys are api_key, base_url, "
            "batch_max_workers, chunk_config, chunk_overlap, chunk_size, context_block, "
            "context_scope, data_source, enable_prompt_caching, expect, file_limit, "
            "frequency_penalty, "
            "granularity, guard_timeout, hitl_timeout, is_operational, json_mode, kind, max_tokens, model_name, "
            "model_vendor, on_empty, output_field, presence_penalty, prompt_debug, "
            "record_concurrency, record_limit, request_timeout, retry, run_mode, split_method, "
            "stop, temperature, tokenizer_model, top_p, vendor_params"
        )
        rendered = _render(tmp_path / "good", [A, _include(defaults={"record_limit": 1})])
        assert _names(rendered) == ["a", "b1", "b2"]

    def test_an_override_of_an_action_the_branch_does_not_define(self, tmp_path):
        message = _refusal(tmp_path / "bad", [A, _include(override={"bb1": {"intent": "x"}})])

        assert message == (
            f"Include 'pair' in {WF}: override names 'bb1', which branch 'pair' "
            "(branches/pair.yml) does not define. Did you mean 'b1'? Branch actions: b1, b2."
        )
        rendered = _render(tmp_path / "good", [A, _include(override={"b1": {"intent": "x"}})])
        assert _names(rendered) == ["a", "b1", "b2"]


class TestTheSchemaFolderCheckSeesTheIncludeJsonMode:
    @pytest.mark.parametrize(
        "include, needs",
        [
            (_include(defaults={"json_mode": True}), True),
            (INCLUDE, False),
            (
                _include(
                    defaults={"json_mode": True},
                    override={"b1": {"json_mode": False}, "b2": {"json_mode": False}},
                ),
                False,
            ),
        ],
        ids=["include-on", "workflow-off", "actions-off"],
    )
    def test_the_rendered_workflow(self, tmp_path, include, needs):
        rendered = _rendered(tmp_path, [A, include], None, workflow_defaults={"json_mode": False})

        assert ConfigRenderingService._workflow_needs_schema(rendered) is needs


def test_include_defaults_give_the_agents_that_the_same_workflow_defaults_give(tmp_path):
    values = {
        "api_key": "OTHER_KEY",
        "granularity": "file",
        "run_mode": "batch",
        "temperature": 0.4,
    }

    included = _loaded(
        tmp_path / "included", [A, _include(defaults=values)], {"pair": _pair([NOTE, B2])}
    )
    flat = _loaded(tmp_path / "flat", [A, NOTE, B2], workflow_defaults=values)

    for name in ("b1", "b2"):
        assert {key: value for key, value in included[name].items() if key != "_include"} == (
            flat[name]
        )
    assert included["b2"]["granularity"] == "File"
    assert str(included["b1"]["run_mode"].value) == "batch"


@pytest.fixture
def cli_project(tmp_path, isolated_user_tools):  # noqa: F811
    def make(actions, branches=None, folder: str = "project", **defaults):
        root = tmp_path / folder
        _write(root, actions, branches, **defaults)
        (root / "tools").mkdir()
        (root / "tools" / "pair_tools.py").write_text(
            TOOLS + "\n\n@udf_tool()\ndef host_z(data, **kwargs):\n    return {'text': 'x'}\n"
        )
        (root / "agent_workflow" / "wf" / "agent_io" / "staging").mkdir(parents=True)
        return root

    return make


def _problem(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith(("  Problem:", "  defaults"))]


class TestAMalformedWorkflowGetsTheRefusalItGetsWithoutAnInclude:
    def test_a_bad_workflow_context_scope_beside_a_removal(self, cli_project, monkeypatch):
        include = _include(remove=["b2"], defaults={"context_scope": {"observe": ["a.text"]}})
        bad = {"context_scope": "bad"}

        code, included, _ = _run(
            cli_project([A, include], workflow_defaults=bad), monkeypatch, "-a", "wf"
        )
        _, inline, _ = _run(
            cli_project([A, B1], folder="inline", workflow_defaults=bad), monkeypatch, "-a", "wf"
        )

        assert code != 0
        assert _problem(included) == _problem(inline)
        assert any("Input should be a valid dictionary" in line for line in included)


class TestTheDocsCatalogShowsWhatInspectShows:
    def test_an_included_action_with_include_defaults(self, cli_project, monkeypatch):
        include = _include(
            defaults={"model_name": "gpt-4.1", "context_scope": {"observe": ["a.text"]}}
        )
        reads_note = {**B2, "context_scope": {"observe": ["b1.note"]}}
        root = cli_project([A, include], {"pair": _pair([NOTE, reads_note])})

        catalog = WorkflowParser.parse_workflow(str(root / WF), root)
        shown = {name: _inspected(root, monkeypatch, name) for name in ("b1", "b2")}

        assert catalog is not None
        assert shown["b1"]["model"] == "gpt-4.1"
        assert catalog["actions"]["b1"]["model"] == "gpt-4.1"
        assert shown["b2"]["context_scope"]["observe"] == ["a.text", "b1.note"]
        for name in ("b1", "b2"):
            observed = catalog["actions"][name]["context_scope"]["observe"]
            assert observed == shown[name]["context_scope"]["observe"]
        assert "model" not in catalog["actions"]["a"]


def _inspected(root, monkeypatch, name: str) -> dict:
    code, lines, _ = _run(root, monkeypatch, "action", "-a", "wf", name, "--json")
    assert code == 0, "\n".join(lines)
    output = "\n".join(lines)
    return json.loads(output[output.index("{") :])
