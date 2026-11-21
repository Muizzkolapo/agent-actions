"""A prompt may read a field its action observes as optional without an `if` around it.

Preflight flags a prompt reference to a field the producer does not guarantee, because
a record without the field fails at the render. A field observed as optional renders
as its default on such a record, so the reference is not flagged; the same reference
without the mark still is.
"""

from __future__ import annotations

from agent_actions.validation.prompt_required_field_validator import (
    find_unguarded_required_refs,
)

PROMPTS = {"retry": "Previous: {{ review.rejected_text }} / {{ review.score }}"}
SCHEMAS = {
    "review": {
        "fields": [
            {"id": "rejected_text", "type": "string", "required": False},
            {"id": "score", "type": "string", "required": False},
        ]
    }
}


def test_the_reference_to_the_optional_field_is_not_flagged():
    findings = find_unguarded_required_refs(
        PROMPTS, SCHEMAS, optional={"retry": {"review.rejected_text"}}
    )

    assert len(findings) == 1
    assert "'review.score'" in findings[0]


def test_both_references_are_flagged_without_the_mark():
    findings = find_unguarded_required_refs(PROMPTS, SCHEMAS)

    assert len(findings) == 2


def test_another_action_s_mark_spares_nothing_here():
    findings = find_unguarded_required_refs(
        PROMPTS, SCHEMAS, optional={"other": {"review.rejected_text", "review.score"}}
    )

    assert len(findings) == 2
