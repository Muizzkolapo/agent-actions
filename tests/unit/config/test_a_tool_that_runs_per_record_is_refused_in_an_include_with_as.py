"""A tool that runs per record is refused inside an include with `as:`, at load.

Its function would get the record keyed by the final names (`c__write`), while it reads
the short names of the branch (`write`): the run stored empty values as a success.
"""

from __future__ import annotations

from tests.unit.config.test_a_workflow_includes_a_branch_file import A, _names, _refusal, _render
from tests.unit.config.test_an_include_as_gives_each_instance_its_own_names import (
    REVIEW,
    WRITE,
    _round,
    _use,
)

WF = "agent_workflow/wf/agent_config/wf.yml"


def _per_record(action: dict) -> dict:
    return {key: value for key, value in action.items() if key != "granularity"}


def test_a_record_tool_in_an_as_include_is_refused_with_the_reason(tmp_path):
    branch = _round([_per_record(WRITE), REVIEW])

    message = _refusal(tmp_path, [A, _use("c")], {"round": branch})

    assert message == (
        f"Branch 'round' (branches/round.yml), included in {WF} as 'c', action 'write': "
        "a tool that runs per record cannot be in an include with 'as:'. Its function would "
        "get the record keyed by the final names of the instance, not by the short names of "
        "the branch. Include the branch without 'as:', or set 'granularity: file' on the tool."
    )


def test_a_tool_that_runs_per_file_loads(tmp_path):
    assert _names(_render(tmp_path, [A, _use("c")], {"round": _round()})) == [
        "a",
        "c__write",
        "c__review",
    ]


def test_a_record_tool_in_an_include_without_as_loads(tmp_path):
    branch = _round([_per_record(WRITE), _per_record(REVIEW)], inputs={"a": "Holds the text"})
    for action in branch["actions"]:
        action["dependencies"] = ["a"] if action["name"] == "write" else ["write"]
        action["context_scope"] = {
            "observe": ["a.text"] if action["name"] == "write" else ["write.text"]
        }
        action.pop("guard", None)

    rendered = _render(tmp_path, [A, {"include": "round", "inputs": {"a": "a"}}], {"round": branch})

    assert _names(rendered) == ["a", "write", "review"]
