"""The two granularities account differently for a record the scope cannot enrich.

FILE mode runs `apply_context_scope_for_records` BEFORE the guard, so an unenrichable
record is removed from the run and written as `DISPOSITION_SKIPPED` with its scope reason
— no guard verdict is ever recorded for it. RECORD mode runs no such pass: the record
reaches the guard, is judged, and only then fails at prompt preparation, which
`_build_prep_failed_result` classifies as FAILED and counts toward terminal-failure
detection.

Neither is obviously wrong, and #1140 asks which surface is right. Both candidate answers
overturn a decision that is already deliberate and documented somewhere:

* making RECORD skip instead contradicts `_build_prep_failed_result`'s docstring, which
  says a prep failure is "a genuine failure of this action ... (matching the batch path)";
* making FILE stop discarding pre-guard contradicts the position-filtering that
  `pipeline.py` and `prefilter_by_guard` rely on to keep the scoped and pre-scope lists
  aligned.

So this file does not choose. It pins what each granularity does today, in one place, so
that whichever answer is taken the change is caught here and has to be argued for rather
than drifting. Two facts worth recording because the issue does not state them:

1. the FILE scope pass runs only for a FILE-granularity **tool or HITL** action
   (`pipeline.py`), so the "fails at render time" option does not apply to a tool action —
   there is no prompt to render;
2. both granularities do ultimately refuse the record; they differ in the disposition
   written and in whether a guard verdict exists at all.
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


class TestFileModeRemovesTheRecordBeforeAnyGuardVerdict:
    def test_the_record_is_skipped_with_its_scope_reason(self):
        prepared, skipped = apply_context_scope_for_records(
            [_record()], _SCOPE, source_data=[_record()], action_name="b"
        )

        assert prepared == []
        assert [s["reason"] for s in skipped] == [OBSERVE_FIELD_MISSING]

    def test_the_skip_names_the_position_so_the_pre_scope_list_stays_aligned(self):
        """`pipeline.py` removes these positions from the list the guard is paired to."""
        _prepared, skipped = apply_context_scope_for_records(
            [_record()], _SCOPE, source_data=[_record()], action_name="b"
        )

        assert skipped[0]["position"] == 0


class TestRecordModeRefusesLaterAndAsAFailure:
    def test_the_same_scope_raises_rather_than_skipping(self):
        """Reached only after the guard has judged the record, so a verdict exists."""
        with pytest.raises(RecordContextError):
            apply_context_scope(_record()["content"], _SCOPE, action_name="b")

    def test_the_error_is_per_record_recoverable_not_fatal(self):
        """online_llm catches it per record and continues with the rest of the file."""
        from agent_actions.errors import ConfigurationError

        assert issubclass(RecordContextError, ConfigurationError)


class TestBothGranularitiesDoRefuseTheRecord:
    """The divergence is in the accounting, not in whether the record runs."""

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
