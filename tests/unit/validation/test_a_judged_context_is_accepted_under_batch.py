"""A judged rule's `context:` refs are accepted on a batch action, as on an online one.

A batch run keeps the values the refs read when it prepares each record, so the judge
gets them once the answers are back. What a ref names is still checked in every run mode.
"""

import pytest

from agent_actions.validation.expectations_validator import (
    _repair_mode_defects,
    find_expectation_defects,
)


def _judged(*refs: str) -> list[dict]:
    return [
        {
            "id": "grounded",
            "type": "llm_judge",
            "field": "summary",
            "params": {"rule": "is grounded", "context": list(refs)},
        }
    ]


ACTIONS = {
    "llm in batch": {"kind": "llm", "model_vendor": "openai", "run_mode": "batch"},
    "llm online": {"kind": "llm", "model_vendor": "openai", "run_mode": "online"},
    "tool under batch": {"kind": "tool", "model_vendor": "tool", "run_mode": "batch"},
    "hitl under batch": {"kind": "hitl", "model_vendor": "hitl", "run_mode": "batch"},
}


@pytest.mark.parametrize("action", ACTIONS.values(), ids=ACTIONS.keys())
def test_no_run_mode_refuses_a_judged_context(action):
    assert _repair_mode_defects(action, {"repair": "none"}, _judged("extract.body")) == []


def _defects(*refs: str) -> list[str]:
    action = {
        **ACTIONS["llm in batch"],
        "expect": {"repair": "none", "expectations": _judged(*refs)},
    }
    found = find_expectation_defects(
        {"summarize": action}, {"extract": {"body"}, "summarize": {"summary"}}
    )
    return found.get("summarize", [])


def test_a_batch_action_s_reference_to_an_upstream_field_has_no_defect():
    assert _defects("extract.body") == []


def test_a_batch_action_s_reference_to_nothing_upstream_is_still_refused():
    assert _defects("extract.notes", "nowhere.body") == [
        "grounded: context reference 'extract.notes' — action 'extract' "
        "does not produce field 'notes'",
        "grounded: context reference 'nowhere.body' names unknown action 'nowhere'",
    ]
