"""A scope-skipped row records which field was missing and which directive wanted it.

`apply_context_scope_for_records` refuses a record it cannot enrich and appends a skip
carrying only a reason string. The diagnosis existed at that moment -- `RecordContextError`
holds `field_ref` and `directive` in its context, and the source-pool branch knows how many
records it searched -- and went to a `debug` log that is off in a normal run. What the user
can see afterwards is the stored disposition, which said `observe_field_missing` and nothing
about which field (#1140).

`DispositionRow` already carries a `detail` column, documented as "extended error message or
context for the disposition", and this path passed `None` for it.
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


class TestTheDetailReachesTheStoredRow:
    """The skip dict carrying a detail is half of it; the column has to be written.

    `pipeline.py` built the seven-tuple inline and passed `None` for `detail`, which is how
    it stayed empty unnoticed. `scope_skip_disposition_rows` is that construction, named so
    the column can be asserted without driving a whole pipeline (#1140).
    """

    def test_the_detail_lands_in_the_seventh_column(self):
        from agent_actions.workflow.pipeline import scope_skip_disposition_rows

        rows = scope_skip_disposition_rows(
            "consume",
            [
                {
                    "source_guid": "g1",
                    "reason": "observe_field_missing",
                    "position": 0,
                    "detail": "context_scope.observe field 'a1.n' not found in this record",
                }
            ],
        )

        assert len(rows) == 1
        assert len(rows[0]) == 7, rows[0]
        assert rows[0][3] == "observe_field_missing"
        assert rows[0][6] == "context_scope.observe field 'a1.n' not found in this record"

    def test_a_skip_with_no_detail_still_writes_a_row(self):
        """Nothing requires the detail: a reason-only skip must still be accounted for."""
        from agent_actions.workflow.pipeline import scope_skip_disposition_rows

        rows = scope_skip_disposition_rows(
            "consume", [{"source_guid": "g1", "reason": "source_unresolved", "position": 0}]
        )

        assert len(rows) == 1
        assert rows[0][6] is None

    def test_a_skip_without_a_source_guid_is_left_out(self):
        """There is nothing to key a disposition on."""
        from agent_actions.workflow.pipeline import scope_skip_disposition_rows

        assert scope_skip_disposition_rows("consume", [{"reason": "source_unresolved"}]) == []
