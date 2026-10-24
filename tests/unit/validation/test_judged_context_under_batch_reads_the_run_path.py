"""A judged context: rule is refused under batch only for an action that batches.

A tool or hitl action under run_mode: batch runs online, where context refs are
available, so its rule must not be refused.
"""

import pytest

from agent_actions.validation.expectations_validator import _repair_mode_defects

JUDGED_WITH_CONTEXT = [
    {
        "id": "grounded",
        "type": "llm_judge",
        "params": {"rule": "is grounded", "context": ["source.text"]},
    }
]


def _context_defects(action: dict) -> list[str]:
    return [
        m
        for m in _repair_mode_defects(action, {"repair": "none"}, JUDGED_WITH_CONTEXT)
        if "context: refs" in m
    ]


@pytest.mark.parametrize("kind", ["tool", "hitl"])
def test_an_online_only_action_under_batch_keeps_its_judged_context(kind):
    assert _context_defects({"kind": kind, "model_vendor": kind, "run_mode": "batch"}) == []


def test_an_llm_action_under_batch_is_still_refused_its_judged_context():
    assert _context_defects({"kind": "llm", "model_vendor": "openai", "run_mode": "batch"}) == [
        "grounded: context: refs are not available under batch run_mode — "
        "the judge would fail every record on a missing context source; "
        "drop context: or run the action online"
    ]
