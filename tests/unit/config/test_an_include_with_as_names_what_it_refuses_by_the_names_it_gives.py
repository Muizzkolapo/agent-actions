"""An include with `as:` refuses a read in words that are true, and reads the names it gives.

A prompt that read a short name was told the branch does not define it; a removal named the
reader by its final name and the include by its branch; a host read of a bound action by its
workflow name passed; the version names of a bound input and single-brace prompt text had
no test.
"""

from __future__ import annotations

import pytest

from agent_actions.config.includes import expand_workflow_includes
from agent_actions.errors import ConfigurationError
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    A,
    Z,
    _names,
    _project,
    _refusal,
    _render,
    _with,
)
from tests.unit.config.test_an_include_as_gives_each_instance_its_own_names import (
    REVIEW,
    WRITE,
    _by_name,
    _round,
    _use,
)

WF = "agent_workflow/wf/agent_config/wf.yml"

TALK = {
    "name": "talk",
    "intent": "talk",
    "prompt": "$round.Talk",
    "schema": {"text": "string"},
    "dependencies": ["write"],
    "context_scope": {"observe": ["write.text"]},
}


def _with_prompt(tmp_path, text: str, actions, branches):
    workflow = _project(tmp_path, actions, branches)
    (tmp_path / "prompt_store" / "round.md").write_text(
        f"{{prompt Talk}}\n{text}\n{{end_prompt}}\n"
    )
    return workflow


def _render_prompt(tmp_path, text: str):
    from agent_actions.prompt.render_workflow import render_pipeline_with_templates

    branch = _round([WRITE, TALK], outputs=["talk"])
    workflow = _with_prompt(tmp_path, text, [A, _use("c")], {"round": branch})
    return render_pipeline_with_templates(
        workflow, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
    )


class TestAPromptThatReadsAShortName:
    def test_the_refusal_says_it_is_a_short_name_and_gives_the_final_name(self, tmp_path):
        with pytest.raises(ConfigurationError) as caught:
            _render_prompt(tmp_path, "Say {{ write.text }}.")

        assert str(caught.value) == (
            f"Branch 'round' (branches/round.yml), included in {WF} as 'c', action 'talk': "
            "reads 'write', a short name of the branch. In an include with 'as:', a prompt "
            "cannot read a short name yet. Write the final name 'c__write'."
        )

    def test_a_short_name_of_an_input_gives_the_action_it_binds(self, tmp_path):
        with pytest.raises(ConfigurationError) as caught:
            _render_prompt(tmp_path, "Say {{ c__write.text }} about {{ spec.text }}.")

        assert "reads 'spec', a short name of the branch" in str(caught.value)
        assert "Write the final name 'a'." in str(caught.value)

    def test_the_final_name_loads(self, tmp_path):
        assert "c__talk" in _render_prompt(tmp_path, "Say {{ c__write.text }}.")

    def test_single_brace_text_is_left_to_the_template_checks(self, tmp_path):
        """It renders as written, so the include check does not read it; `agac inspect`
        reports it as it does in a workflow without an include."""
        assert "c__talk" in _render_prompt(tmp_path, "Say {{ c__write.text }} as {write.text}.")


class TestAnInputBoundToAVersionedAction:
    VOTE = {
        "name": "vote",
        "kind": "tool",
        "granularity": "file",
        "impl": "host_vote",
        "schema": {"text": "string"},
        "intent": "vote",
        "dependencies": ["a"],
        "versions": {"range": [1, 2]},
        "context_scope": {"observe": ["a.text"]},
    }

    def _reader(self, observe):
        return _with(REVIEW, dependencies=["feed"], context_scope={"observe": observe}, guard=None)

    def _branch(self, observe):
        reader = self._reader(observe)
        del reader["guard"]
        return _round([reader], inputs={"feed": "The votes"}, outputs=["review"])

    def test_each_instance_reads_the_versions_of_its_input_by_their_short_names(self, tmp_path):
        branch = self._branch(["feed_1.text", "feed_2.text"])
        includes = [
            {"include": "round", "as": name, "inputs": {"feed": "vote"}} for name in ("p", "q")
        ]

        actions = _by_name(_render(tmp_path, [A, self.VOTE, *includes], {"round": branch}))

        for name in ("p", "q"):
            assert actions[f"{name}__review"]["context_scope"] == {
                "observe": ["vote_1.text", "vote_2.text"]
            }

    def test_a_version_the_target_does_not_have_is_refused(self, tmp_path):
        branch = self._branch(["feed_3.text"])
        include = {"include": "round", "as": "p", "inputs": {"feed": "vote"}}

        message = _refusal(tmp_path, [A, self.VOTE, include], {"round": branch})

        assert "reads 'feed_3', which the branch does not define" in message


class TestAHostReadThroughAnInput:
    def test_a_bound_action_read_by_its_workflow_name_is_refused(self, tmp_path):
        reader = _with(REVIEW, context_scope={"observe": ["write.text", "a.text"]})
        message = _refusal(tmp_path, [A, _use("c", spec="a")], {"round": _round([WRITE, reader])})

        assert message == (
            f"Branch 'round' (branches/round.yml), included in {WF} as 'c', action 'review': "
            "reads 'a', a workflow action, by its workflow name. Inside an include with 'as:', "
            "read it through its input: 'spec'."
        )

    def test_the_same_read_through_the_input_loads(self, tmp_path):
        reader = _with(REVIEW, context_scope={"observe": ["write.text", "spec.text"]})
        rendered = _render(tmp_path, [A, _use("c", spec="a")], {"round": _round([WRITE, reader])})

        assert _by_name(rendered)["c__review"]["context_scope"] == {
            "observe": ["c__write.text", "a.text"]
        }

    def test_an_input_bound_to_the_action_of_its_own_name_is_still_read_by_it(self, tmp_path):
        spec = _with(Z, name="spec")
        rendered = _render(tmp_path, [A, spec, _use("c2", spec="spec")], {"round": _round()})

        assert _names(rendered)[-1] == "c2__review"


def test_a_removal_names_the_include_by_its_label_and_the_reader_by_its_short_name(tmp_path):
    include = {**_use("c2"), "remove": ["write"]}

    message = _refusal(tmp_path, [A, include], {"round": _round()})

    assert message == (
        f"Include 'round' as 'c2' in {WF}: remove names 'write' of branch 'round' "
        "(branches/round.yml), but 'review' still reads it. Remove the readers too, or "
        "override them so that they do not read it."
    )


def test_expand_alone_keeps_a_bound_read_by_its_input(tmp_path):
    host = {"name": "wf", "description": "d", "actions": [A, _use("c", spec="a")]}
    expanded, _ = expand_workflow_includes(host, WF, {"round": _round()}, ["round"])

    assert [action["name"] for action in expanded["actions"]] == ["a", "c__write", "c__review"]
