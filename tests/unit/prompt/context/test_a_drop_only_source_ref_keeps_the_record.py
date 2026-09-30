"""FILE mode must not discard a record because the action only DROPS from source.

`has_source_refs` decides whether to build the source index, and the skip was gated on the
same flag. A `drop` names a field to withhold, so an unresolvable source means there is
nothing to withhold and the record is complete without it -- a record carrying no source
cannot leak one. RECORD mode proceeds with such a record, so the two granularities
disagreed about whether it survives.

Found while checking #1099, whose premise runs the other way.
"""

from agent_actions.prompt.context.scope_application import (
    apply_context_scope,
    apply_context_scope_for_records,
)

_POOL = [
    {"source_guid": "other1", "content": {"doc": {"x": 1}}},
    {"source_guid": "other2", "content": {"doc": {"x": 2}}},
]


def _file_mode(scope: dict):
    records = [{"source_guid": "absent", "content": {"a1": {"n": 5}}}]
    return apply_context_scope_for_records(records, scope, source_data=_POOL, action_name="b")


class TestFileModeKeepsWhatItCannotLeak:
    def test_a_drop_only_source_ref_keeps_the_record(self):
        prepared, skipped = _file_mode({"observe": ["a1.n"], "drop": ["source.secret"]})

        assert len(prepared) == 1, "nothing to withhold, so nothing to skip for"
        assert skipped == []

    def test_no_source_ref_at_all_keeps_the_record(self):
        prepared, skipped = _file_mode({"observe": ["a1.n"]})

        assert len(prepared) == 1
        assert skipped == []


class TestFileModeStillSkipsWhatItCannotSupply:
    """The narrowing must not weaken the case #869 established."""

    def test_an_observe_naming_source_still_skips(self):
        prepared, skipped = _file_mode({"observe": ["source.x"]})

        assert prepared == []
        assert [s["reason"] for s in skipped] == ["source_unresolved"]

    def test_a_passthrough_naming_source_still_skips(self):
        prepared, skipped = _file_mode({"passthrough": ["source.x"]})

        assert prepared == []
        assert [s["reason"] for s in skipped] == ["source_unresolved"]

    def test_a_drop_alongside_an_observe_still_skips(self):
        """The drop must not excuse an observe that genuinely needs the content."""
        prepared, skipped = _file_mode({"observe": ["source.x"], "drop": ["source.secret"]})

        assert prepared == []
        assert [s["reason"] for s in skipped] == ["source_unresolved"]


class TestTheTwoGranularitiesNowAgree:
    """The point of the change: same record, same pool miss, same verdict.

    RECORD mode refuses an observe/passthrough that needs source by raising
    RecordContextError, which the online strategy turns into a prep-failed tombstone —
    a different mechanism from FILE mode's skip, but the same outcome for the record.
    """

    @staticmethod
    def _record_mode_survives(scope: dict) -> bool:
        try:
            apply_context_scope({"a1": {"n": 5}}, scope, action_name="b")
        except Exception:
            return False
        return True

    def test_both_keep_a_drop_only_reference(self):
        prepared, _ = _file_mode({"observe": ["a1.n"], "drop": ["source.secret"]})

        assert len(prepared) == 1
        assert self._record_mode_survives({"observe": ["a1.n"], "drop": ["source.secret"]})

    def test_both_refuse_an_observe_that_needs_source(self):
        prepared, _ = _file_mode({"observe": ["source.x"]})

        assert prepared == []
        assert not self._record_mode_survives({"observe": ["source.x"]})

    def test_both_refuse_a_passthrough_that_needs_source(self):
        prepared, _ = _file_mode({"passthrough": ["source.x"]})

        assert prepared == []
        assert not self._record_mode_survives({"passthrough": ["source.x"]})
