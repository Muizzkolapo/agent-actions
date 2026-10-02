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


class TestAnUnresolvedSourceSaysWhatWasSearched:
    def test_the_detail_names_the_pool_it_searched(self):
        """The reason says the guid matched nothing; the detail says how large the pool
        was, which is what distinguishes an empty pool from a genuine miss."""
        records = [{"source_guid": "ghost", "content": {"a1": {"x": 1}}}]
        source_data = [{"source_guid": "real-1", "content": {"url": "u"}}]

        skipped = _skip(records, scope={"observe": ["source.url"]}, source_data=source_data)

        assert len(skipped) == 1, skipped
        assert skipped[0]["reason"] == "source_unresolved"
        detail = skipped[0].get("detail")
        assert detail, "the skip carried no detail at all"
        assert "1" in detail, detail

    def test_an_empty_pool_is_distinguishable_from_a_miss(self):
        records = [{"source_guid": "ghost", "content": {"a1": {"x": 1}}}]

        empty = _skip(records, scope={"observe": ["source.url"]}, source_data=[])
        populated = _skip(
            records,
            scope={"observe": ["source.url"]},
            source_data=[{"source_guid": "real-1", "content": {"url": "u"}}],
        )

        assert empty[0].get("detail") != populated[0].get("detail")
