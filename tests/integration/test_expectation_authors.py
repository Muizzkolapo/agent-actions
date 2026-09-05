"""Seventeen ways to write an expect block, each through the real preflight.

Every author is a working project under ``fixtures/expectation_authors``. What is
pinned is the verdict, and for a refusal the phrase that names the correction — a
refusal that does not say what to change is worth no more than silence.
"""

from pathlib import Path

import pytest

from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.services.workflow_inspector import WorkflowInspector

PROJECT = Path(__file__).parent / "fixtures" / "expectation_authors"

ACCEPTED = [
    "batch_field_rules",
    "custom_check",
    "field_scoped_rules",
    "inline_rules",
    "judge_votes_and_budget",
    "pair_and_pattern_rules",
    "record_expression",
    "repair_auto",
    "row_condition_on_optional_field",
    "shared_suite",
    "tool_action",
    "verdict_guard",
]

REFUSED = {
    "array_member_rule": [
        "nested member 'text'",
        "a selector reaches top-level fields only",
        "write a custom check",
    ],
    "judged_context_under_batch": [
        "not available under batch run_mode",
        "run the action online",
    ],
    "many_mistakes": [
        "field 'no_such_field' is not produced by this action",
        "arguments belong under params:",
        "unknown rule key 'sevrity' — did you mean 'severity'?",
        "severity 'fail' is now 'error'",
        "unknown type 'vibe_check'",
    ],
    "old_flat_shape": [
        "type 'accepted_values' requires parameter 'values'",
        "move values there",
        "severity 'fail' is now 'error'",
    ],
    "repair_auto_at_file_granularity": [
        "cannot run at file granularity",
        "use repair: none or record granularity",
    ],
}


def _preflight(author: str) -> None:
    WorkflowInspector(author, project_root=PROJECT).validate()


@pytest.mark.parametrize("author", ACCEPTED)
def test_the_block_is_accepted(author):
    _preflight(author)


@pytest.mark.parametrize(("author", "phrases"), sorted(REFUSED.items()))
def test_the_refusal_names_what_to_change(author, phrases):
    with pytest.raises(PreFlightValidationError) as exc:
        _preflight(author)
    message = str(exc.value)
    for phrase in phrases:
        assert phrase in message, f"{author}: no mention of {phrase!r}\n{message}"


def test_a_refusal_never_advises_what_the_author_already_did():
    """The empty-schema remedy must not answer a file that has rules."""
    with pytest.raises(PreFlightValidationError) as exc:
        _preflight("array_member_rule")
    assert "declare them under a field" not in str(exc.value)


def test_every_author_has_a_verdict():
    on_disk = {
        d.name for d in (PROJECT / "agent_workflow").iterdir() if (d / "agent_config").is_dir()
    }
    assert on_disk == set(ACCEPTED) | set(REFUSED)
