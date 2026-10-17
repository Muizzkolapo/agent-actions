"""A namespace the record cannot supply carries what the record shows about why (1489).

The render error used to say "likely guard-filtered or guard-skipped" for every such
namespace. The builder now records which of these the record shows -- a guard on the
upstream skipped it, the upstream wrote null without a guard skip, the upstream's
output is not on the record, or it holds none of the observed fields -- and the
render error states that, naming a guard only when one skipped the record.
"""

import pytest

from agent_actions.errors.operations import TemplateVariableError
from agent_actions.prompt.context.null_namespace import is_null_namespace
from agent_actions.prompt.context.scope_builder import build_field_context_with_history
from agent_actions.prompt.service import PromptPreparationService

INDICES = {"extract": 0, "classify": 1, "summarize": 2}
CONFIG = {
    "dependencies": ["extract", "classify"],
    "context_scope": {"observe": ["extract.text", "classify.topic"]},
}


def _guard_skip(action: str) -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "action": action,
        "from": None,
        "to": "guard_skipped",
        "reason": "guard_skip",
        "detail": None,
    }


def _classify_namespace(content: dict, history: list | None = None):
    item = {"content": content, "source_guid": "sg-1"}
    if history is not None:
        item["_state_history"] = history
    context = build_field_context_with_history(
        agent_name="summarize",
        agent_config=CONFIG,
        agent_indices=INDICES,
        current_item=item,
        context_scope=CONFIG["context_scope"],
    )
    return context["classify"]


def _render_error(namespace) -> str:
    with pytest.raises(TemplateVariableError) as exc_info:
        PromptPreparationService._render_prompt_template(
            "{{ extract.text }} {{ classify.topic }}",
            {"extract": {"text": "x"}, "classify": namespace},
            agent_name="summarize",
        )
    hints = exc_info.value.null_namespace_hints
    assert list(hints) == ["classify"]
    return hints["classify"]["remediation"]


def test_a_guard_skip_the_record_shows_is_named():
    ns = _classify_namespace(
        {"extract": {"text": "x"}, "classify": None}, history=[_guard_skip("classify")]
    )

    assert is_null_namespace(ns)
    message = _render_error(ns)
    assert message.startswith(
        "Namespace 'classify' is null on this record: a guard on 'classify' skipped it."
    )
    assert "likely" not in message


def test_a_null_namespace_without_a_guard_skip_names_no_guard():
    """Another action's guard skip is not this namespace's."""
    ns = _classify_namespace(
        {"extract": {"text": "x"}, "classify": None}, history=[_guard_skip("extract")]
    )

    message = _render_error(ns)
    assert message.startswith("Namespace 'classify' is null on this record:")
    assert "guard on 'classify' skipped" not in message
    assert "guard-skipped" not in message
    assert "guard-filtered" not in message


def test_a_namespace_absent_from_the_record_is_said_to_be_absent():
    ns = _classify_namespace({"extract": {"text": "x"}})

    assert is_null_namespace(ns)
    message = _render_error(ns)
    assert message.startswith(
        "Namespace 'classify' is not on this record: no output of 'classify' reached it."
    )
    assert "guard" not in message.lower()
    assert "dependencies" in message


def test_an_output_without_any_observed_field_names_the_fields():
    ns = _classify_namespace({"extract": {"text": "x"}, "classify": {"label": "a"}})

    assert is_null_namespace(ns)
    message = _render_error(ns)
    assert message.startswith(
        "Namespace 'classify' has none of the fields 'summarize' observes from it "
        "(observes: topic; 'classify' has: label)."
    )
    assert "guard" not in message.lower()
    assert "null" not in message.split(".")[0]


def test_a_legacy_none_namespace_names_no_guard():
    message = _render_error(None)

    assert message.startswith("Namespace 'classify' is null on this record.")
    assert "guard-" not in message
