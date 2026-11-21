"""What the load makes of a `- loop:` entry, and what it refuses."""

from __future__ import annotations

import copy

import pytest

from agent_actions.config.includes import expand_workflow_includes
from agent_actions.config.loops import expand_loops, finish_loops
from agent_actions.errors import ConfigurationError
from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.output.response.expander_action_types import process_guard_config
from agent_actions.prompt.aliases import with_alias_header
from agent_actions.prompt.context.scope_inference import expand_version_base_names

WF = "agent_config/wf.yml"

BRANCH = {
    "branch": "question_round",
    "description": "Write, then check",
    "inputs": {"spec": "the topic", "prior": "the previous check"},
    "outputs": ["check"],
    "actions": [
        {
            "name": "write",
            "intent": "Write",
            "prompt": "$wf.Write",
            "schema": "draft",
            "dependencies": ["spec"],
            "context_scope": {"observe": ["spec.topic", "prior.*"]},
        },
        {
            "name": "check",
            "kind": "tool",
            "impl": "check_question",
            "intent": "Check",
            "schema": "verdict",
            "dependencies": ["write"],
            "context_scope": {"observe": ["write.question", "spec.*", "prior.reasons"]},
        },
    ],
}


def _loop(**extra):
    return {
        "loop": "round",
        "include": "question_round",
        "max_iterations": 3,
        "inputs": {"spec": "spec"},
        "feedback": {"prior": "check"},
        "until": "check.passed == true",
        "result": "check",
        **extra,
    }


def _workflow(loop=None, after=None):
    return {
        "name": "wf",
        "actions": [
            {"name": "spec", "kind": "tool", "impl": "make_spec", "intent": "x", "schema": "s"},
            loop if loop is not None else _loop(),
            *(after or []),
        ],
    }


def _expanded(data=None, branch=None):
    branches = {"question_round": branch or BRANCH}
    data, _ = expand_workflow_includes(data or _workflow(), WF, branches, list(branches))
    return expand_loops(data)


def _by_name(data):
    return {a["name"]: a for a in data["actions"]}


def _refusal(data=None, branch=None):
    with pytest.raises(ConfigurationError) as caught:
        _expanded(data, branch)
    return str(caught.value)


def _branch(**changes):
    branch = copy.deepcopy(BRANCH)
    for name, keys in changes.items():
        action = next(a for a in branch["actions"] if a["name"] == name)
        action.update(keys)
    return branch


def test_a_loop_of_three_is_three_instances_of_the_branch_and_a_pick_named_after_it():
    names = list(_by_name(_expanded()))

    assert names == [
        "spec",
        "round_iter1__write",
        "round_iter1__check",
        "round_iter2__write",
        "round_iter2__check",
        "round_iter3__write",
        "round_iter3__check",
        "round",
    ]


def test_no_iteration_action_reads_as_a_version_of_another_name():
    names = list(_by_name(_expanded()))

    for base in ("round", "round_iter", "round_iter1", "write", "check"):
        assert expand_version_base_names([base], names) == [base]


def test_iteration_1_reads_no_feedback_and_binds_it_to_none():
    actions = _by_name(_expanded())
    write, check = actions["round_iter1__write"], actions["round_iter1__check"]

    assert write["dependencies"] == ["spec"]
    assert write["context_scope"] == {"observe": ["spec.topic"]}
    assert check["context_scope"] == {
        "observe": ["round_iter1__write.question", "spec.*"],
    }
    assert write["_include"]["names"]["prior"] == "none"
    assert "guard" not in write and "_sends_elsewhere" not in write


def test_the_alias_header_of_iteration_1_sets_the_feedback_input_to_none():
    names = _by_name(_expanded())["round_iter1__write"]["_include"]["names"]
    prompt = "Write {{ spec.topic }}{% if prior %} again: {{ prior.reasons }}{% endif %}"

    header = with_alias_header(prompt, names)

    assert header.startswith("{% set prior = none %}")


def test_from_iteration_2_the_entry_takes_the_previous_result_and_its_guard_ends_the_loop():
    actions = _by_name(_expanded())

    for k in (2, 3):
        write = actions[f"round_iter{k}__write"]
        previous = f"round_iter{k - 1}__check"
        assert write["dependencies"] == [previous]
        assert write["guard"] == {
            "condition": f"NOT ({previous}.passed == true)",
            "on_false": "filter",
            "passthrough_on_error": False,
        }
        assert write["_sends_elsewhere"] is True
        assert write["context_scope"] == {"observe": ["spec.topic", f"{previous}.*"]}
        assert write["_include"]["names"]["prior"] == previous


def test_an_action_below_the_entry_keeps_its_own_dependencies_and_no_guard():
    check = _by_name(_expanded())["round_iter2__check"]

    assert check["dependencies"] == ["round_iter2__write"]
    assert "guard" not in check and "_sends_elsewhere" not in check
    assert "round_iter1__check.reasons" in check["context_scope"]["observe"]


def test_the_pick_takes_the_last_iteration_first_and_gathers():
    pick = _by_name(_expanded())["round"]

    of = ["round_iter3__check", "round_iter2__check", "round_iter1__check"]
    assert pick["impl"] == "agac.pick"
    assert pick["_builtin"]["tool"] == "pick"
    assert pick["_builtin"]["of"] == of
    assert pick["_builtin"]["loop"]["max_iterations"] == 3
    assert pick["dependencies"] == of
    assert pick["_gathers"] is True


def test_every_iteration_action_carries_its_loop_and_iteration():
    actions = _by_name(_expanded())

    loop = actions["round_iter2__check"]["_include"]["loop"]
    assert (loop["name"], loop["iteration"], loop["until"]) == ("round", 2, "check.passed == true")


def test_a_loop_of_one_has_no_guard_and_no_feedback():
    actions = _by_name(_expanded(_workflow(_loop(max_iterations=1))))

    assert list(actions) == ["spec", "round_iter1__write", "round_iter1__check", "round"]
    assert "guard" not in actions["round_iter1__write"]


# -- the guard that ends the loop, record by record ---------------------------


def _passes(record):
    write = _by_name(_expanded())["round_iter2__write"]
    agent: dict = {}
    process_guard_config(agent, write)
    return GuardEvaluator().evaluate(record, agent["guard"]).should_execute


def test_the_guard_runs_a_record_again_whose_check_failed():
    assert _passes({"round_iter1__check": {"passed": False}}) is True


def test_the_guard_sends_away_a_record_whose_check_passed():
    assert _passes({"round_iter1__check": {"passed": True}}) is False


def test_the_guard_runs_no_record_that_holds_no_check_of_the_previous_iteration():
    """A record that left the loop earlier holds no row there: NOT of an unknown is not true."""
    assert _passes({"spec": {"topic": "t"}}) is False
    assert _passes({"round_iter1__check": None}) is False
    assert _passes({"round_iter1__check": {}}) is False
    assert _passes({"round_iter1__check": {"reasons": "x"}}) is False


# -- refusals ----------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 11, "3", True, None])
def test_max_iterations_must_be_a_whole_number_from_1_to_10(count):
    assert "'max_iterations:' must be a whole number from 1 to 10" in _refusal(
        _workflow(_loop(max_iterations=count))
    )


def test_an_unknown_key_is_refused():
    assert "unknown key times" in _refusal(_workflow(_loop(times=3)))


def test_a_loop_name_that_reads_as_a_version_is_refused():
    assert "reads as a version" in _refusal(_workflow(_loop(loop="round_2")))


def test_a_loop_naming_no_branch_file_is_refused():
    assert "names no branch file" in _refusal(_workflow(_loop(include="nope")))


def test_feedback_naming_no_input_of_the_branch_is_refused():
    message = _refusal(_workflow(_loop(feedback={"previous": "check"})))
    assert "'feedback:' names 'previous'" in message


def test_feedback_also_bound_under_inputs_is_refused():
    message = _refusal(_workflow(_loop(inputs={"spec": "spec", "prior": "spec"})))
    assert "'prior' is under both 'inputs:' and 'feedback:'" in message


def test_feedback_from_an_action_the_branch_does_not_output_is_refused():
    message = _refusal(_workflow(_loop(feedback={"prior": "write"})))
    assert "'write' is not listed under 'outputs:'" in message


def test_a_result_the_branch_does_not_output_is_refused():
    assert "'result: write' is not listed under 'outputs:'" in _refusal(
        _workflow(_loop(result="write", feedback={}))
    )


@pytest.mark.parametrize(
    ("until", "reads"),
    [
        ("spec.topic == 'x'", "spec.topic"),
        ("passed == true", "passed"),
        ("source.flag == true", "source.flag"),
    ],
)
def test_until_reading_anything_but_a_field_of_a_branch_action_is_refused(until, reads):
    assert f"reads '{reads}'" in _refusal(_workflow(_loop(until=until)))


def test_until_reading_an_action_below_the_result_is_refused():
    loop = _loop(until="check.passed == true", result="write", feedback={})
    branch = {**BRANCH, "outputs": ["check", "write"]}
    assert "that run up to 'write'" in _refusal(_workflow(loop), branch)


def test_until_that_does_not_parse_is_refused():
    assert "is not a valid condition" in _refusal(_workflow(_loop(until="check.passed ==")))


def test_a_udf_until_is_refused():
    assert "is a UDF guard" in _refusal(_workflow(_loop(until="udf:done")))


def test_an_entry_action_with_a_guard_of_its_own_is_refused():
    branch = _branch(write={"guard": {"condition": "spec.topic != ''", "on_false": "skip"}})
    assert "'write', which starts branch 'question_round'" in _refusal(branch=branch)


def test_a_guard_reading_a_feedback_input_is_refused():
    branch = _branch(check={"guard": {"condition": "prior.passed == false", "on_false": "skip"}})
    assert "the guard of 'check' reads a feedback input" in _refusal(branch=branch)


def test_a_hand_written_loop_key_on_an_include_is_refused():
    data = _workflow({"include": "question_round", "_loop": {"name": "x"}})
    assert "'_loop' is set by the load" in _refusal(data)


# -- after the schemas compile -----------------------------------------------


def _compiled(data):
    for action in data["actions"]:
        local = (action.get("_include") or {}).get("local_name")
        if local == "check":
            action["schema"] = {
                "name": "verdict",
                "fields": [
                    {"id": "passed", "type": "boolean"},
                    {"id": "reasons", "type": "string"},
                ],
            }
        elif local == "write":
            action["schema"] = {"name": "draft", "fields": [{"id": "question", "type": "string"}]}
    return data


def test_the_pick_takes_the_schema_of_the_result(tmp_path):
    data = _compiled(_expanded())

    finish_loops(data, WF, tmp_path)

    schema = _by_name(data)["round"]["schema"]
    assert schema["name"] == "round_result"
    assert [f["id"] for f in schema["fields"]] == ["passed", "reasons"]


def test_until_reading_a_field_the_schema_does_not_have_is_refused(tmp_path):
    data = _compiled(_expanded(_workflow(_loop(until="check.pass == true"))))

    with pytest.raises(ConfigurationError, match="the schema of 'check' has no field 'pass'"):
        finish_loops(data, WF, tmp_path)


def test_an_action_outside_the_loop_reading_an_iteration_is_refused(tmp_path):
    reader = {
        "name": "publish",
        "intent": "x",
        "prompt": "Publish {{ round_iter2__check.reasons }}",
        "schema": "p",
        "dependencies": ["round"],
    }
    data = _compiled(_expanded(_workflow(after=[reader])))

    with pytest.raises(ConfigurationError, match="reads 'round_iter2__check'.*read 'round'"):
        finish_loops(data, WF, tmp_path)


def test_an_action_outside_the_loop_reading_the_loop_name_is_accepted(tmp_path):
    reader = {
        "name": "publish",
        "intent": "x",
        "prompt": "Publish {{ round.reasons }}",
        "schema": "p",
        "dependencies": ["round"],
        "context_scope": {"observe": ["round.*"]},
    }
    data = _compiled(_expanded(_workflow(after=[reader])))

    finish_loops(data, WF, tmp_path)


def test_a_branch_action_at_file_granularity_is_refused(tmp_path):
    branch = _branch(check={"granularity": "File"})
    data = _compiled(_expanded(branch=branch))

    with pytest.raises(ConfigurationError, match="'check' of branch 'question_round' runs at File"):
        finish_loops(data, WF, tmp_path)
