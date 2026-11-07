"""A scope refusal records which field was missing and which directive wanted it.

`apply_context_scope_for_records` refuses a record it cannot enrich and appends a skip
whose `detail` names the field, or how many pooled records were searched. The pipeline
turns the refusal into the record's failure, so the detail is what the stored disposition
holds and what the run line prints.
"""

from agent_actions.prompt.context.scope_application import apply_context_scope_for_records


def _skip(records, scope, source_data=None):
    _, skipped = apply_context_scope_for_records(
        records, scope, action_name="consume", source_data=source_data
    )
    return skipped


class TestAnObserveFieldMissingSaysWhichOne:
    def test_the_detail_names_the_field_and_the_directive(self):
        records = [{"source_guid": "g1", "content": {"a1": {"tier": "secret"}}}]
        scope = {"observe": ["a1.n"]}

        skipped = _skip(records, scope)

        assert len(skipped) == 1, skipped
        detail = skipped[0].get("detail")
        assert detail, "the skip carried no detail at all"
        assert "a1.n" in detail, detail
        assert "observe" in detail, detail

    def test_the_reason_is_unchanged(self):
        """The detail is added beside the reason, not instead of it: `reason` is what
        anything grouping or counting dispositions keys on."""
        records = [{"source_guid": "g1", "content": {"a1": {"tier": "secret"}}}]

        skipped = _skip(records, scope={"observe": ["a1.n"]})

        assert skipped[0]["reason"] == "observe_field_missing"
        assert skipped[0]["position"] == 0
        assert skipped[0]["source_guid"] == "g1"

    def test_a_different_missing_field_gives_a_different_detail(self):
        """Non-tautological: the detail has to come from the error, not be a fixed string."""
        records = [{"source_guid": "g1", "content": {"a1": {"tier": "secret"}}}]

        first = _skip(records, scope={"observe": ["a1.n"]})[0]["detail"]
        second = _skip(records, scope={"observe": ["a1.other_name"]})[0]["detail"]

        assert first != second, (first, second)
        assert "a1.other_name" in second, second


def _pool(n: int) -> list[dict]:
    return [{"source_guid": f"r{i}", "content": {"url": "u"}} for i in range(n)]


class TestAnUnresolvedSourceSaysWhatWasSearched:
    def test_the_detail_names_how_many_records_were_searched(self):
        """The reason says the guid matched nothing. The count says whether it searched one
        record or a thousand, which is the difference between a misconfigured pool and a
        genuine miss -- and the reason alone cannot carry it."""
        records = [{"source_guid": "ghost", "content": {"a1": {"x": 1}}}]

        skipped = _skip(records, scope={"observe": ["source.url"]}, source_data=_pool(3))

        assert len(skipped) == 1, skipped
        assert skipped[0]["reason"] == "source_unresolved"
        assert "3 pooled records" in (skipped[0].get("detail") or ""), skipped

    def test_the_count_is_the_real_pool_size(self):
        """Non-tautological, and the reason an earlier version of this test was wrong: a
        pool of one and a pool of three both reach this branch with the same reason, so only
        the count distinguishes them. (An *empty* pool does not reach it at all -- it comes
        out as observe_field_missing -- so the count can never read 0 here.)"""
        records = [{"source_guid": "ghost", "content": {"a1": {"x": 1}}}]

        one = _skip(records, scope={"observe": ["source.url"]}, source_data=_pool(1))
        three = _skip(records, scope={"observe": ["source.url"]}, source_data=_pool(3))

        assert one[0]["reason"] == three[0]["reason"] == "source_unresolved"
        assert "1 pooled records" in one[0]["detail"], one
        assert "3 pooled records" in three[0]["detail"], three

    def test_an_empty_pool_is_a_different_reason_entirely(self):
        """Pinned because it is counter-intuitive: with no pool there is nothing to resolve
        against, so `source.url` is simply an absent observe field."""
        records = [{"source_guid": "ghost", "content": {"a1": {"x": 1}}}]

        skipped = _skip(records, scope={"observe": ["source.url"]}, source_data=[])

        assert skipped[0]["reason"] == "observe_field_missing", skipped
        assert "source.url" in skipped[0]["detail"], skipped


class TestTheDetailReachesTheFailedResult:
    """The skip dict carrying a detail is half of it; the record's failure has to carry it.

    `pipeline.py` keys each refusal by its position for the processor, which fails the
    record with that text once the guard has admitted it. Both halves are asserted here
    without driving a whole pipeline.
    """

    def test_the_detail_is_keyed_by_the_records_position(self):
        from agent_actions.workflow.pipeline import scope_refusals

        assert scope_refusals(
            [
                {
                    "source_guid": "g1",
                    "reason": "observe_field_missing",
                    "position": 1,
                    "detail": "context_scope.observe field 'a1.n' not found in this record",
                }
            ]
        ) == {1: "context_scope.observe field 'a1.n' not found in this record"}

    def test_a_refusal_with_no_detail_fails_with_its_reason(self):
        from agent_actions.workflow.pipeline import scope_refusals

        assert scope_refusals(
            [{"source_guid": "g1", "reason": "source_unresolved", "position": 0}]
        ) == {0: "source_unresolved"}

    def test_the_failure_is_the_pre_scope_record_with_the_detail_as_its_error(self):
        from agent_actions.processing.types import ProcessingStatus
        from agent_actions.processing.unified import refused_failure

        original = {"source_guid": "g1", "content": {"a1": {}}}
        result = refused_failure(
            original, "context_scope.observe field 'a1.n' not found in this record"
        )

        assert result.status is ProcessingStatus.FAILED
        assert result.error == "context_scope.observe field 'a1.n' not found in this record"
        assert result.source_guid == "g1"
        assert result.input_record is original

    def test_a_refusal_without_a_source_guid_is_still_a_failure(self):
        """The record is in the run's count whether or not it can be keyed by identity."""
        from agent_actions.processing.unified import refused_failure

        result = refused_failure({"content": {}}, "no pool")

        assert result.source_guid is None
        assert result.error == "no pool"

    def test_refused_records_keep_their_positions_beside_the_enriched_ones(self):
        from agent_actions.workflow.pipeline import with_refused_in_place

        records = [{"i": 0}, {"i": 1}, {"i": 2}]
        enriched = [{"i": 0, "e": True}, {"i": 2, "e": True}]

        placed = with_refused_in_place(enriched, {1: "why"}, records)

        assert placed == [{"i": 0, "e": True}, {"i": 1}, {"i": 2, "e": True}]
        assert placed[1] is records[1]
