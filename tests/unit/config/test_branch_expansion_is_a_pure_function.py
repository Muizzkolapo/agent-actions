"""The include expansion reads parsed data and branch content only, and changes neither."""

import copy

import pytest

from agent_actions.config.includes import expand_workflow_includes
from agent_actions.errors import ConfigurationError

WF = "agent_workflow/wf/agent_config/wf.yml"

PAIR = {
    "branch": "pair",
    "description": "Two tool actions",
    "inputs": {"a": "Holds the text"},
    "outputs": ["b2"],
    "actions": [
        {"name": "b1", "kind": "tool", "impl": "one", "intent": "i", "dependencies": ["a"]},
        {"name": "b2", "kind": "tool", "impl": "two", "intent": "i", "dependencies": ["b1"]},
    ],
}
HOST = {
    "name": "wf",
    "description": "d",
    "actions": [
        {"name": "a", "kind": "tool", "impl": "host", "intent": "i"},
        {"include": "pair", "inputs": {"a": "a"}},
        {"name": "c", "kind": "tool", "impl": "host", "intent": "i", "dependencies": ["b2"]},
    ],
}


def test_the_expansion_splices_the_branch_and_leaves_its_inputs_unchanged():
    host, branches = copy.deepcopy(HOST), {"pair": copy.deepcopy(PAIR)}

    expanded, inclusions = expand_workflow_includes(host, WF, branches, ["pair"])

    assert [action["name"] for action in expanded["actions"]] == ["a", "b1", "b2", "c"]
    assert [(i.instance, i.workflow_file) for i in inclusions] == [("pair", WF)]
    assert host == HOST
    assert branches == {"pair": PAIR}


def test_each_splice_is_its_own_copy():
    expanded, _ = expand_workflow_includes(HOST, WF, {"pair": PAIR}, ["pair"])
    expanded["actions"][1]["dependencies"].append("x")

    again, _ = expand_workflow_includes(HOST, WF, {"pair": PAIR}, ["pair"])

    assert again["actions"][1]["dependencies"] == ["a"]


def test_data_without_an_include_is_returned_as_it_is():
    plain = {"name": "wf", "actions": [{"name": "a"}]}

    assert expand_workflow_includes(plain, WF, {}, []) == (plain, [])
    assert expand_workflow_includes({"default_agent_config": {}}, WF, {}, []) == (
        {"default_agent_config": {}},
        [],
    )


def test_a_missing_branch_with_no_branch_files_says_none_were_found():
    with pytest.raises(ConfigurationError) as caught:
        expand_workflow_includes(HOST, WF, {}, [])

    assert str(caught.value) == (
        f"Include 'pair' in {WF}: no branch file branches/pair.yml. Branch files found: none."
    )
