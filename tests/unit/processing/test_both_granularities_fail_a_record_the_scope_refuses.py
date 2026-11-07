"""Both granularities fail a record the scope cannot enrich, and account for it the same way.

FILE mode runs `apply_context_scope_for_records` BEFORE the guard, so the scoped and
pre-scope lists stay aligned by position; it used to remove an unenrichable record from
the run as a `skipped` disposition outside every count, while RECORD mode failed the same
record at prompt preparation. The skip hid data loss in an aggregate: a roll-up over
eleven records read as complete when twelve were staged, and the run was green.

Now the FILE pass still refuses the record before the guard, keeping the position
alignment, but the pipeline turns the refusal into the record's failure: it is counted,
its disposition is `failed` with a reason naming every missing field, and `agac retry`
can reach it. RECORD mode is unchanged in outcome and now names every missing field too.
This file pins that parity.
"""

import pytest

from agent_actions.errors import RecordContextError
from agent_actions.prompt.context.scope_application import (
    apply_context_scope,
    apply_context_scope_for_records,
)
from agent_actions.record.reasons import OBSERVE_FIELD_MISSING

_SCOPE = {"observe": ["a1.n"], "drop": ["a1.tier"]}


def _record() -> dict:
    return {"source_guid": "g1", "content": {"a1": {"tier": "secret"}}}


class TestFileModeRefusesBeforeTheGuardAndFailsTheRecord:
    def test_the_record_is_refused_with_its_scope_reason_and_the_field_named(self):
        prepared, skipped = apply_context_scope_for_records(
            [_record()], _SCOPE, source_data=[_record()], action_name="b"
        )

        assert prepared == []
        assert [s["reason"] for s in skipped] == [OBSERVE_FIELD_MISSING]
        assert skipped[0]["detail"] == "context_scope.observe field 'a1.n' not found in this record"

    def test_the_refusal_names_the_position_so_the_pre_scope_list_stays_aligned(self):
        """`pipeline.py` removes these positions from the list the guard is paired to."""
        _prepared, skipped = apply_context_scope_for_records(
            [_record()], _SCOPE, source_data=[_record()], action_name="b"
        )

        assert skipped[0]["position"] == 0

    def test_the_refusal_becomes_the_records_failure(self):
        """What the pipeline does with the refusal: a failed result the collector writes."""
        from agent_actions.processing.types import ProcessingStatus
        from agent_actions.workflow.pipeline import scope_refusals

        records = [_record()]
        _prepared, skipped = apply_context_scope_for_records(
            records, _SCOPE, source_data=[_record()], action_name="b"
        )

        (failure,) = scope_refusals(skipped, records)

        assert failure.status is ProcessingStatus.FAILED
        assert failure.error == "context_scope.observe field 'a1.n' not found in this record"
        assert failure.source_guid == "g1"
        assert failure.input_record is records[0]


class TestRecordModeFailsTheSameRecordWithTheSameWords:
    def test_the_same_scope_raises_a_per_record_error(self):
        """Reached only after the guard has judged the record, so a verdict exists."""
        with pytest.raises(RecordContextError) as raised:
            apply_context_scope(_record()["content"], _SCOPE, action_name="b")

        assert raised.value.context["field_ref"] == "a1.n"

    def test_the_error_is_per_record_recoverable_not_fatal(self):
        """online_llm catches it per record and continues with the rest of the file."""
        from agent_actions.errors import ConfigurationError

        assert issubclass(RecordContextError, ConfigurationError)

    def test_two_missing_fields_are_named_by_both_granularities(self):
        scope = {"observe": ["a1.n", "a1.m"]}

        with pytest.raises(RecordContextError) as raised:
            apply_context_scope(_record()["content"], scope, action_name="b")
        _prepared, skipped = apply_context_scope_for_records(
            [_record()], scope, source_data=[_record()], action_name="b"
        )

        both = "context_scope.observe fields 'a1.n', 'a1.m' not found in this record"
        assert str(raised.value) == both
        assert skipped[0]["detail"] == both


class TestBothGranularitiesDoRefuseTheRecord:
    def test_neither_granularity_lets_it_reach_the_action(self):
        prepared, _skipped = apply_context_scope_for_records(
            [_record()], _SCOPE, source_data=[_record()], action_name="b"
        )
        assert prepared == []

        with pytest.raises(RecordContextError):
            apply_context_scope(_record()["content"], _SCOPE, action_name="b")

    def test_an_enrichable_record_is_kept_by_both(self):
        """The control: without the missing field neither path refuses anything."""
        enrichable = {"source_guid": "g1", "content": {"a1": {"tier": "secret", "n": 1}}}

        prepared, skipped = apply_context_scope_for_records(
            [dict(enrichable)], _SCOPE, source_data=[dict(enrichable)], action_name="b"
        )
        assert len(prepared) == 1 and skipped == []

        prompt_context, _llm, _pt = apply_context_scope(
            dict(enrichable["content"]), _SCOPE, action_name="b"
        )
        assert prompt_context["a1"]["n"] == 1
        assert "tier" not in prompt_context["a1"], "the drop still applies on both"
