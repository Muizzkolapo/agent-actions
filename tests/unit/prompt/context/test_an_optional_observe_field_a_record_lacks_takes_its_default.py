"""An observe entry marked optional never fails a record that lacks its field.

The field resolves to `None`, or to the default its entry states, whether the field is
missing from its namespace, null in it, or the whole namespace is null because a guard
skipped the upstream action. The same field without the mark still fails the record.
The scope below is what the config boundary hands the run: plain references in
`observe`, the optional ones under `optional` with their value when missing.
"""

from __future__ import annotations

import pytest

from agent_actions.config.types import RunMode
from agent_actions.errors import RecordContextError
from agent_actions.prompt.context.null_namespace import SKIPPED_NAMESPACE, is_null_namespace
from agent_actions.prompt.context.scope_application import (
    apply_context_scope,
    apply_context_scope_for_records,
)
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.workflow.pipeline_file_mode import extract_tool_input

OPTIONAL = {
    "observe": ["spec.text", "review.rejected_text"],
    "optional": {"review.rejected_text": None},
}
DEFAULTED = {
    "observe": ["spec.text", "review.rejected_text"],
    "optional": {"review.rejected_text": "nothing rejected"},
}
REQUIRED = {"observe": ["spec.text", "review.rejected_text"]}


def _context(review: object) -> dict:
    return {"spec": {"text": "s"}, "review": review}


class TestTheFieldIsMissingFromItsNamespace:
    def test_it_resolves_to_none_and_the_record_is_not_refused(self):
        """The LLM context and the prompt context both hold the field as None."""
        prompt_context, llm_context, _ = apply_context_scope(
            _context({"verdict": "ok"}), OPTIONAL, action_name="retry"
        )

        assert llm_context == {"spec": {"text": "s"}, "review": {"rejected_text": None}}
        assert prompt_context["review"] == {"rejected_text": None}

    def test_it_resolves_to_the_default_its_entry_states(self):
        prompt_context, llm_context, _ = apply_context_scope(
            _context({"verdict": "ok"}), DEFAULTED, action_name="retry"
        )

        assert llm_context["review"] == {"rejected_text": "nothing rejected"}
        assert prompt_context["review"] == {"rejected_text": "nothing rejected"}

    def test_the_same_field_without_the_mark_still_fails_the_record(self):
        """The record fails with RecordContextError, which names the field."""
        with pytest.raises(RecordContextError) as raised:
            apply_context_scope(_context({"verdict": "ok"}), REQUIRED, action_name="retry")

        assert (
            str(raised.value)
            == "context_scope.observe field 'review.rejected_text' not found in namespace 'review'"
        )

    def test_a_required_field_missing_beside_it_is_the_only_one_named(self):
        scope = {
            "observe": ["review.rejected_text", "review.score"],
            "optional": {"review.rejected_text": None},
        }

        with pytest.raises(RecordContextError) as raised:
            apply_context_scope(_context({"verdict": "ok"}), scope, action_name="retry")

        assert raised.value.context["field_ref"] == "review.score"
        assert "field_refs" not in raised.value.context

    def test_a_field_the_record_has_is_read_as_it_is(self):
        _, llm_context, _ = apply_context_scope(
            _context({"rejected_text": "too long"}), DEFAULTED, action_name="retry"
        )

        assert llm_context["review"] == {"rejected_text": "too long"}

    def test_a_default_that_is_a_list_is_not_shared_between_records(self):
        scope = {"observe": ["review.reasons"], "optional": {"review.reasons": []}}

        _, first, _ = apply_context_scope(_context({}), scope, action_name="retry")
        first["review"]["reasons"].append("edited by one record")
        _, second, _ = apply_context_scope(_context({}), scope, action_name="retry")

        assert second["review"]["reasons"] == []
        assert scope["optional"]["review.reasons"] == []


class TestTheFieldIsNull:
    def test_a_null_value_takes_the_stated_default(self):
        _, llm_context, _ = apply_context_scope(
            _context({"rejected_text": None}), DEFAULTED, action_name="retry"
        )

        assert llm_context["review"] == {"rejected_text": "nothing rejected"}

    def test_a_null_value_with_no_default_stays_none(self):
        _, llm_context, _ = apply_context_scope(
            _context({"rejected_text": None}), OPTIONAL, action_name="retry"
        )

        assert llm_context["review"] == {"rejected_text": None}

    @pytest.mark.parametrize("value", ["", 0, False, []])
    def test_an_empty_value_is_a_value_and_keeps_out_the_default(self, value):
        _, llm_context, _ = apply_context_scope(
            _context({"rejected_text": value}), DEFAULTED, action_name="retry"
        )

        assert llm_context["review"] == {"rejected_text": value}


class TestTheWholeNamespaceIsNull:
    @pytest.mark.parametrize("skipped", [SKIPPED_NAMESPACE, None], ids=["sentinel", "legacy"])
    def test_the_field_resolves_as_a_skipped_namespace_field_always_did(self, skipped):
        _, optional, _ = apply_context_scope(_context(skipped), OPTIONAL, action_name="retry")
        _, required, _ = apply_context_scope(_context(skipped), REQUIRED, action_name="retry")

        assert optional == required == {"spec": {"text": "s"}, "review": {"rejected_text": None}}

    def test_a_stated_default_is_what_it_resolves_to(self):
        _, llm_context, _ = apply_context_scope(
            _context(SKIPPED_NAMESPACE), DEFAULTED, action_name="retry"
        )

        assert llm_context["review"] == {"rejected_text": "nothing rejected"}

    def test_the_namespace_stays_null_and_still_answers_for_the_field(self):
        prompt_context, _, _ = apply_context_scope(
            _context(SKIPPED_NAMESPACE), DEFAULTED, action_name="retry"
        )

        review = prompt_context["review"]
        assert is_null_namespace(review)
        assert not review
        assert review == SKIPPED_NAMESPACE
        assert review["rejected_text"] == "nothing rejected"

    def test_a_namespace_the_record_does_not_carry_at_all_is_no_failure_either(self):
        _, llm_context, _ = apply_context_scope(
            {"spec": {"text": "s"}}, DEFAULTED, action_name="retry"
        )

        assert llm_context["review"] == {"rejected_text": "nothing rejected"}

    def test_without_the_mark_that_namespace_still_fails_the_record(self):
        with pytest.raises(RecordContextError, match="not found at runtime"):
            apply_context_scope({"spec": {"text": "s"}}, REQUIRED, action_name="retry")


PROMPT = (
    "Spec: {{ spec.text }} | "
    "{% if review %}Reviewed{% else %}Not reviewed{% endif %} | "
    "Rejected: [{{ review.rejected_text }}]"
)


def _rendered(scope: dict, review: object) -> str:
    result = PromptPreparationService.prepare_prompt_with_field_context(
        {"agent_type": "retry", "prompt": PROMPT, "context_scope": scope},
        "retry",
        {},
        field_context=_context(review),
    )
    return result.formatted_prompt


class TestWhatThePromptSees:
    def test_a_missing_field_with_no_default_renders_as_a_null_value_does(self):
        missing = _rendered(OPTIONAL, {"verdict": "ok"})
        null = _rendered(REQUIRED, {"rejected_text": None})

        assert missing == null == "Spec: s | Reviewed | Rejected: []"

    def test_a_missing_field_renders_its_default(self):
        assert _rendered(DEFAULTED, {"verdict": "ok"}).endswith("Rejected: [nothing rejected]")

    def test_a_prompt_reads_the_field_of_a_skipped_upstream(self):
        assert _rendered(OPTIONAL, SKIPPED_NAMESPACE) == "Spec: s | Not reviewed | Rejected: []"
        assert _rendered(DEFAULTED, SKIPPED_NAMESPACE).endswith("Rejected: [nothing rejected]")

    def test_a_field_named_as_the_null_marker_s_own_attribute_reads_its_default(self):
        scope = {"observe": ["review.reason"], "optional": {"review.reason": "none given"}}
        result = PromptPreparationService.prepare_prompt_with_field_context(
            {"agent_type": "retry", "prompt": "[{{ review.reason }}]", "context_scope": scope},
            "retry",
            {},
            field_context=_context(SKIPPED_NAMESPACE),
        )

        assert result.formatted_prompt == "[none given]"

    def test_without_the_mark_the_prompt_still_cannot_read_a_skipped_upstream(self):
        from agent_actions.errors import TemplateVariableError

        with pytest.raises(TemplateVariableError, match="a guard on 'review' skipped it"):
            _rendered(REQUIRED, SKIPPED_NAMESPACE)

    def test_a_required_field_read_beside_an_optional_one_keeps_the_skip_diagnosis(self):
        """The namespace answers for `rejected_text` only; `score` is still a read of a
        skipped upstream, diagnosed as one."""
        from agent_actions.errors import TemplateVariableError

        scope = {
            "observe": ["review.rejected_text", "review.score"],
            "optional": {"review.rejected_text": None},
        }
        config = {
            "agent_type": "retry",
            "prompt": "[{{ review.rejected_text }}] [{{ review.score }}]",
            "context_scope": scope,
        }

        with pytest.raises(TemplateVariableError) as raised:
            PromptPreparationService.prepare_prompt_with_field_context(
                config, "retry", {}, field_context=_context(SKIPPED_NAMESPACE)
            )

        message = str(raised.value)
        assert "undefined variables: score" in message
        assert (
            "Namespace 'review' is null on this record: a guard on 'review' skipped it" in message
        )
        assert "has no field" not in message


def _record(review: object) -> dict:
    return {
        "source_guid": "g1",
        "content": {"spec": {"text": "s"}, "review": review},
        "_state_history": [],
    }


def _prepared(scope: dict, review: object, mode: RunMode, kind: str = "llm"):
    record = _record(review)
    return PromptPreparationService.prepare_prompt_with_context(
        {
            "agent_type": "retry",
            "kind": kind,
            "prompt": PROMPT,
            "dependencies": ["review"],
            "context_scope": scope,
        },
        "retry",
        record["content"],
        mode=mode,
        agent_indices={"spec": 0, "review": 1, "retry": 2},
        current_item=record,
    )


@pytest.mark.parametrize("mode", [RunMode.ONLINE, RunMode.BATCH], ids=["online", "batch"])
class TestOnlineAndBatchPrepareTheRecordAlike:
    """Both modes build a record's context from the record itself, where a declared
    field the namespace lacks is refused before the scope is applied."""

    def test_the_record_is_prepared_and_the_field_is_none(self, mode):
        result = _prepared(OPTIONAL, {"verdict": "ok", "other": 1}, mode)

        assert result.llm_context["review"] == {"rejected_text": None}
        assert result.formatted_prompt == "Spec: s | Reviewed | Rejected: []"

    def test_the_record_is_prepared_with_the_default(self, mode):
        result = _prepared(DEFAULTED, {"verdict": "ok"}, mode)

        assert result.llm_context["review"] == {"rejected_text": "nothing rejected"}
        assert result.formatted_prompt.endswith("Rejected: [nothing rejected]")

    def test_an_upstream_the_record_shows_no_output_of_reads_as_not_run(self, mode):
        result = _prepared(DEFAULTED, None, mode)

        assert result.llm_context["review"] == {"rejected_text": "nothing rejected"}
        assert "Not reviewed" in result.formatted_prompt

    def test_the_same_field_without_the_mark_still_fails_the_record(self, mode):
        scope = {"observe": ["spec.text", "review.verdict", "review.rejected_text"]}

        with pytest.raises(RecordContextError, match="rejected_text"):
            _prepared(scope, {"verdict": "ok"}, mode)

    def test_a_tool_action_s_input_holds_the_field(self, mode):
        result = _prepared(DEFAULTED, {"verdict": "ok"}, mode, kind="tool")

        assert result.llm_context["review"] == {"rejected_text": "nothing rejected"}


class TestAFileToolIsHandedTheField:
    def _handed(self, scope: dict, review: object) -> tuple[list[dict], list[dict]]:
        record = _record(review)
        prepared, skipped = apply_context_scope_for_records(
            [record], scope, action_name="roll_up", source_data=[record]
        )
        return [extract_tool_input(row, scope) for row in prepared], skipped

    def test_a_missing_field_is_handed_as_none_under_its_key(self):
        handed, skipped = self._handed(OPTIONAL, {"verdict": "ok"})

        assert skipped == []
        assert handed == [{"text": "s", "rejected_text": None}]

    def test_a_missing_field_is_handed_as_its_default(self):
        handed, _ = self._handed(DEFAULTED, {"verdict": "ok"})

        assert handed == [{"text": "s", "rejected_text": "nothing rejected"}]

    def test_a_field_of_a_skipped_upstream_is_handed_too(self):
        handed, skipped = self._handed(DEFAULTED, None)

        assert skipped == []
        assert handed == [{"text": "s", "rejected_text": "nothing rejected"}]

    def test_a_field_the_record_has_is_handed_as_it_is(self):
        handed, _ = self._handed(DEFAULTED, {"rejected_text": "too long"})

        assert handed == [{"text": "s", "rejected_text": "too long"}]

    def test_the_stored_namespace_is_not_given_the_field(self):
        record = _record({"verdict": "ok"})
        prepared, _ = apply_context_scope_for_records(
            [record], DEFAULTED, action_name="roll_up", source_data=[record]
        )

        assert prepared[0]["content"]["review"] == {"verdict": "ok"}

    def test_the_same_field_without_the_mark_still_refuses_the_record(self):
        handed, skipped = self._handed(REQUIRED, {"verdict": "ok"})

        assert handed == []
        assert skipped[0]["detail"] == (
            "context_scope.observe field 'review.rejected_text' not found in this record"
        )
