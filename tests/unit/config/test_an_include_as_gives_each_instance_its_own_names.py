"""An include with `as:` prefixes each branch action with the instance name, and every
reference inside the branch names the action of its own instance."""

from __future__ import annotations

import copy

import pytest

from agent_actions.config.includes import expand_workflow_includes, renamed_clause
from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    WF,
    A,
    C,
    Z,
    _agents,
    _names,
    _refusal,
    _render,
    _with,
)

WRITE = {
    "name": "write",
    "kind": "tool",
    "granularity": "file",
    "impl": "round_write",
    "schema": {"text": "string"},
    "intent": "write",
    "dependencies": ["spec"],
    "context_scope": {"observe": ["spec.text"]},
}
REVIEW = {
    "name": "review",
    "kind": "tool",
    "granularity": "file",
    "impl": "round_review",
    "schema": {"text": "string"},
    "intent": "review",
    "dependencies": ["write"],
    "context_scope": {"observe": ["write.text"]},
    "guard": {"condition": 'write.text != "write.text"', "on_false": "filter"},
}


def _round(actions=None, **over):
    branch = {
        "branch": "round",
        "description": "One question round",
        "inputs": {"spec": "Holds the specification"},
        "outputs": ["review"],
        "actions": copy.deepcopy(actions if actions is not None else [WRITE, REVIEW]),
    }
    branch.update(over)
    return branch


def _use(prefix: str, **inputs: str) -> dict:
    return {"include": "round", "as": prefix, "inputs": inputs or {"spec": "a"}}


def _by_name(rendered: dict) -> dict[str, dict]:
    return {action["name"]: action for action in rendered["actions"]}


def _expanded(actions, branch=None) -> dict[str, dict]:
    host = {"name": "wf", "description": "d", "actions": copy.deepcopy(actions)}
    expanded, _ = expand_workflow_includes(host, WF, {"round": branch or _round()}, ["round"])
    return {action["name"]: action for action in expanded["actions"]}


class TestOneBranchServesSeveralInstances:
    def test_one_branch_used_with_two_prefixes_renders_two_sets_of_actions(self, tmp_path):
        rendered = _render(tmp_path, [A, _use("c"), _use("c2")], {"round": _round()})
        actions = _by_name(rendered)

        assert _names(rendered) == ["a", "c__write", "c__review", "c2__write", "c2__review"]
        assert actions["c__write"]["impl"] == actions["c2__write"]["impl"] == "round_write"
        assert actions["c2__review"]["_include"] == {
            "branch": "round",
            "instance": "c2",
            "local_name": "review",
            "branch_file": "branches/round.yml",
            "names": {"write": "c2__write", "review": "c2__review", "spec": "a"},
        }

    def test_each_instance_loads_as_an_ordinary_workflow(self, tmp_path):
        agents = _agents(
            tmp_path,
            [
                A,
                _use("c"),
                _use("c2"),
                _with(
                    C, dependencies=["c2__review"], context_scope={"observe": ["c2__review.text"]}
                ),
            ],
            {"round": _round()},
        )

        assert list(agents) == ["a", "c__write", "c__review", "c2__write", "c2__review", "c"]
        assert agents["c2__review"]["dependencies"] == ["c2__write"]

    def test_a_dependency_and_an_observe_name_the_sibling_of_the_same_instance(self, tmp_path):
        actions = _by_name(_render(tmp_path, [A, _use("c"), _use("c2")], {"round": _round()}))

        for prefix in ("c", "c2"):
            review = actions[f"{prefix}__review"]
            assert review["dependencies"] == [f"{prefix}__write"]
            assert review["context_scope"] == {"observe": [f"{prefix}__write.text"]}

    def test_a_guard_naming_a_sibling_resolves_per_instance(self, tmp_path):
        actions = _by_name(_render(tmp_path, [A, _use("c"), _use("c2")], {"round": _round()}))
        record = {"c__write": {"text": "x"}, "c2__write": {"text": "write.text"}}

        verdicts = {}
        for prefix in ("c", "c2"):
            clause = actions[f"{prefix}__review"]["guard"]["condition"]
            assert clause == f'{prefix}__write.text != "write.text"'
            verdicts[prefix] = WhereClauseParser().parse(clause).ast.evaluate(record)

        assert verdicts == {"c": True, "c2": False}

    def test_version_consumption_and_an_inline_judge_context_name_the_same_instance(self):
        vote = {
            "name": "vote",
            "kind": "tool",
            "impl": "round_vote",
            "intent": "vote",
            "dependencies": ["spec"],
            "versions": {"range": [1, 2]},
            "context_scope": {"observe": ["spec.text"]},
        }
        tally = {
            "name": "tally",
            "kind": "llm",
            "intent": "tally",
            "prompt": "$round.Tally",
            "dependencies": ["vote"],
            "version_consumption": {"source": "vote", "pattern": "merge"},
            "context_scope": {"observe": ["vote.text", "vote_1.text"]},
            "expect": {
                "expectations": [
                    {
                        "type": "llm_judge",
                        "params": {"context": ["vote.text", "spec.text"], "rubric": "r"},
                    }
                ]
            },
        }
        actions = _expanded([A, _use("c2")], _round([vote, tally], outputs=["tally"]))

        assert list(actions) == ["a", "c2__vote", "c2__tally"]
        tally_c2 = actions["c2__tally"]
        assert tally_c2["version_consumption"] == {"source": "c2__vote", "pattern": "merge"}
        assert tally_c2["context_scope"] == {"observe": ["c2__vote.text", "c2__vote_1.text"]}
        assert tally_c2["expect"]["expectations"][0]["params"]["context"] == [
            "c2__vote.text",
            "a.text",
        ]
        assert actions["c2__vote"]["_include"]["names"]["vote_2"] == "c2__vote_2"

    def test_versions_in_an_instance_expand_under_the_prefixed_name(self, tmp_path):
        vote = _with(WRITE, name="vote", versions={"range": [1, 2]})
        tally = _with(
            REVIEW,
            name="tally",
            guard=None,
            dependencies=["vote"],
            version_consumption={"source": "vote", "pattern": "merge"},
            context_scope={"observe": ["vote.text"]},
        )
        del tally["guard"]
        rendered = _render(
            tmp_path, [A, _use("c2")], {"round": _round([vote, tally], outputs=["tally"])}
        )

        assert _names(rendered) == ["a", "c2__vote_1", "c2__vote_2", "c2__tally"]
        assert _by_name(rendered)["c2__vote_2"]["_version_context"]["base_name"] == "c2__vote"

    def test_a_trailing_question_mark_on_an_observe_is_kept(self):
        reader = _with(WRITE, context_scope={"observe": ["spec.text?", "spec?", "source.id?"]})
        actions = _expanded([A, _use("c2")], _round([reader], outputs=["write"]))

        assert actions["c2__write"]["context_scope"] == {"observe": ["a.text?", "a?", "source.id?"]}

    def test_the_include_defaults_name_the_actions_of_the_instance(self):
        include = {**_use("c2"), "defaults": {"context_scope": {"observe": ["spec.text"]}}}
        actions = _expanded([A, include])

        assert actions["c2__write"]["_include"]["defaults"] == {
            "context_scope": {"observe": ["a.text"]}
        }


class TestInputsBindAnyAction:
    def test_two_instances_bound_to_different_inputs(self, tmp_path):
        rendered = _render(
            tmp_path,
            [A, Z, _use("c", spec="a"), _use("c2", spec="z")],
            {"round": _round()},
        )
        actions = _by_name(rendered)

        assert actions["c__write"]["dependencies"] == ["a"]
        assert actions["c__write"]["context_scope"] == {"observe": ["a.text"]}
        assert actions["c2__write"]["dependencies"] == ["z"]
        assert actions["c2__write"]["context_scope"] == {"observe": ["z.text"]}

    def test_round_two_reads_the_review_of_round_one_through_an_input(self, tmp_path):
        reviser = _with(
            WRITE,
            dependencies=["spec", "previous"],
            context_scope={"observe": ["spec.text", "previous.text"]},
        )
        branch = _round(
            [reviser, REVIEW],
            inputs={"spec": "Holds the specification", "previous": "The last review"},
        )
        rendered = _render(
            tmp_path,
            [A, _use("c", spec="a", previous="a"), _use("c2", spec="a", previous="c__review")],
            {"round": branch},
        )
        write_c2 = _by_name(rendered)["c2__write"]

        assert write_c2["dependencies"] == ["a", "c__review"]
        assert write_c2["context_scope"] == {"observe": ["a.text", "c__review.text"]}

    def test_an_input_bound_to_an_internal_of_the_other_instance_is_refused(self, tmp_path):
        message = _refusal(
            tmp_path, [A, _use("c"), _use("c2", spec="c__write")], {"round": _round()}
        )

        assert message == (
            f"Include 'round' as 'c2' in {WF}: input 'spec' is bound to 'c__write', which branch "
            "'round' (branches/round.yml) does not list under outputs. Outputs of 'round': review."
        )

    def test_the_host_reads_an_output_of_an_instance_by_its_final_name(self, tmp_path):
        reader = _with(
            C, dependencies=["c2__review"], context_scope={"observe": ["c2__review.text"]}
        )
        assert (
            _names(_render(tmp_path / "good", [A, _use("c2"), reader], {"round": _round()}))[-1]
            == "c"
        )

        internal = _with(
            C, dependencies=["c2__write"], context_scope={"observe": ["c2__write.text"]}
        )
        message = _refusal(tmp_path / "bad", [A, _use("c2"), internal], {"round": _round()})
        assert message == (
            f"Action 'c' in {WF} reads 'c2__write', which branch 'round' (branches/round.yml) "
            "does not list under outputs. Outputs of 'round': review."
        )


class TestAShortNameNothingGivesIsRefused:
    @pytest.mark.parametrize(
        "over",
        [
            {"context_scope": {"observe": ["write.text", "draft.text"]}},
            {"guard": {"condition": 'draft.text != ""', "on_false": "filter"}},
            {"dependencies": ["write", "draft"]},
        ],
        ids=["observe", "guard", "dependencies"],
    )
    def test_a_short_name_the_group_does_not_define_and_no_binding_gives(self, tmp_path, over):
        branch = _round([WRITE, _with(REVIEW, **over)])
        message = _refusal(tmp_path / "bad", [A, _use("c2")], {"round": branch})

        assert message == (
            f"Branch 'round' (branches/round.yml), included in {WF} as 'c2', action 'review': "
            "reads 'draft', which the branch does not define and no input of include 'c2' "
            "binds. Branch actions: write, review. Inputs: spec."
        )
        assert _names(_render(tmp_path / "good", [A, _use("c2")], {"round": _round()}))[-1] == (
            "c2__review"
        )

    def test_a_host_action_read_by_its_own_name_inside_an_instance_is_refused(self, tmp_path):
        reader = _with(REVIEW, context_scope={"observe": ["write.text", "z.text"]})
        message = _refusal(tmp_path, [A, Z, _use("c2")], {"round": _round([WRITE, reader])})

        assert message == (
            f"Branch 'round' (branches/round.yml), included in {WF} as 'c2', action 'review': "
            "reads 'z', which is not a branch action or a declared input. Declare it under "
            "'inputs:'."
        )


class TestTheAsEntryIsRefused:
    @pytest.mark.parametrize(
        "prefix, reason",
        [
            ("c__x", "the name contains '__', which is reserved for instance names."),
            ("1c", "the name does not start with a letter."),
            ("c_", "the name ends with '_'."),
        ],
    )
    def test_an_instance_name_that_cannot_prefix_an_action(self, tmp_path, prefix, reason):
        message = _refusal(tmp_path, [A, _use(prefix)], {"round": _round()})

        assert message == (
            f"Include 'round' in {WF}: 'as: {prefix}': {reason} "
            "Use letters, digits and single underscores, starting with a letter."
        )

    @pytest.mark.parametrize("prefix", ["", 3, None])
    def test_an_instance_name_that_is_not_text(self, tmp_path, prefix):
        message = _refusal(tmp_path, [A, _use(prefix)], {"round": _round()})

        assert message == f"Include 'round' in {WF}: 'as' must name the instance, got {prefix!r}."

    def test_two_includes_with_one_instance_name(self, tmp_path):
        message = _refusal(tmp_path, [A, _use("c"), _use("c")], {"round": _round()})

        assert message == (
            f"Workflow 'wf' ({WF}) includes branch 'round' (branches/round.yml) twice with the "
            "instance name 'c'. Give each include its own instance name with 'as:'."
        )

    def test_an_instance_named_like_another_included_branch(self, tmp_path):
        other = _round(branch="other")
        message = _refusal(
            tmp_path,
            [A, {"include": "other", "inputs": {"spec": "a"}}, _use("other")],
            {"round": _round(), "other": other},
        )

        assert message == (
            f"Workflow 'wf' ({WF}) includes branch 'other' (branches/other.yml) and branch "
            "'round' (branches/round.yml) with the instance name 'other'. Give each include "
            "its own instance name with 'as:'."
        )

    @pytest.mark.parametrize(
        "host, short, meaning",
        [(_with(Z, name="write"), "write", "c2__write"), (_with(Z, name="spec"), "spec", "a")],
        ids=["action", "input"],
    )
    def test_a_short_name_that_is_also_a_workflow_action(self, tmp_path, host, short, meaning):
        message = _refusal(tmp_path, [A, host, _use("c2")], {"round": _round()})

        assert message == (
            f"Include 'round' as 'c2' in {WF}: the short name '{short}' of branch 'round' "
            f"(branches/round.yml) is also an action of workflow 'wf'. Inside the include it "
            f"means '{meaning}', so the branch could not tell the two apart. Rename one of them."
        )

    def test_an_input_bound_to_the_action_of_its_own_name_is_no_clash(self, tmp_path):
        spec = _with(Z, name="spec")
        rendered = _render(tmp_path, [A, spec, _use("c2", spec="spec")], {"round": _round()})

        assert _by_name(rendered)["c2__write"]["dependencies"] == ["spec"]

    def test_a_removed_action_that_a_sibling_reads_names_the_reader(self, tmp_path):
        include = {**_use("c2"), "remove": ["write"]}
        message = _refusal(tmp_path, [A, include], {"round": _round()})

        assert message == (
            f"Include 'c2' in {WF}: remove names 'write' of branch 'round' (branches/round.yml), "
            "but 'c2__review' still reads it. Remove the readers too, or override them so that "
            "they do not read it."
        )


@pytest.mark.parametrize(
    "clause, expected",
    [
        ('write.text == "write.text"', 'c2__write.text == "write.text"'),
        ("write.text == 'it\\'s write.x'", "c2__write.text == 'it\\'s write.x'"),
        ('write.text == "say \\"write.x\\""', 'c2__write.text == "say \\"write.x\\""'),
        ("NOT (write.ok == TRUE)", "NOT (c2__write.ok == TRUE)"),
        ("not write.ok", "not c2__write.ok"),
        (
            "((write.a > 1) AND (spec.b < 2 OR source.c IN ['write', \"spec.d\"]))",
            "((c2__write.a > 1) AND (a.b < 2 OR source.c IN ['write', \"spec.d\"]))",
        ),
        (
            "write.a IS NULL OR write.b IS NOT NULL",
            "c2__write.a IS NULL OR c2__write.b IS NOT NULL",
        ),
        ("LENGTH(write.a) BETWEEN 1.5 AND 3", "LENGTH(c2__write.a) BETWEEN 1.5 AND 3"),
        ("writer.a == write", "writer.a == write"),
        ("udf:write_check", "udf:write_check"),
    ],
    ids=[
        "double-quoted-name",
        "escaped-single-quote",
        "escaped-double-quote",
        "not",
        "lowercase-not",
        "nested-parentheses-and-in-list",
        "null-checks",
        "function-and-number",
        "longer-name-and-bare-word",
        "udf",
    ],
)
def test_a_guard_clause_renames_only_the_action_at_the_root_of_a_field_path(clause, expected):
    renamed = renamed_clause(clause, {"write": "c2__write", "spec": "a"})

    assert renamed == expected
    if not clause.startswith("udf:"):
        before = WhereClauseParser().parse(clause)
        after = WhereClauseParser().parse(renamed)
        assert before.success and after.success
        assert repr(after.ast.root).replace("c2__write.", "write.").replace(
            "'a.", "'spec."
        ) == repr(before.ast.root)
