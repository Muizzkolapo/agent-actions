"""A FILE-mode record that carries its own ``source`` namespace resolves against it
when neither identity hop matches the pool, the way the RECORD-mode twin already does.

``processing/source_resolution.resolve_source_content`` checks the record's content for
a ``source`` key before it looks at any guid. The FILE-mode resolver had no such rule:
it tried ``source_guid``, then ``parent_source_guid``, and returned ``None`` against a
non-empty pool — which the caller turns into a ``source_unresolved`` skip even though
the row already holds the namespace the scope asked for. A run where that happens to
every record then fails the action on a ``prefilter_by_guard`` length mismatch.

The fallback is last, not first: a row whose guid resolves keeps taking the pool's
source, so rows that resolve today resolve identically.
"""

from agent_actions.processing.source_resolution import resolve_source_content
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records

POOL = [
    {"source_guid": "ANCESTOR", "content": {"source": {"url": "http://pool.com"}}},
    {"source_guid": "OTHER", "content": {"source": {"url": "http://other.com"}}},
]

SCOPE = {"observe": ["source.url", "a1.i"]}


def carrying(url, *, source_guid="MINTED", parent_source_guid=None):
    """A minted row whose content carries the source namespace it was built with."""
    record = {"source_guid": source_guid, "content": {"source": {"url": url}, "a1": {"i": 1}}}
    if parent_source_guid:
        record["parent_source_guid"] = parent_source_guid
    return record


def scope_pass(records, pool=POOL, scope=None):
    """The FILE-mode pass every FILE-granularity action runs its records through."""
    return apply_context_scope_for_records(
        records, scope or SCOPE, action_name="test", source_data=pool
    )


def observed_urls(enriched):
    return [record["content"]["url"] for record in enriched]


class TestTheCarriedNamespaceIsTheLastResort:
    def test_a_row_whose_identities_both_miss_resolves_against_what_it_carries(self):
        enriched, skipped = scope_pass([carrying("http://carried.com")])

        assert skipped == []
        assert observed_urls(enriched) == ["http://carried.com"]

    def test_a_row_that_names_no_producer_at_all_resolves(self):
        """The ``source_index: None`` output of a FILE tool: a guid minted in the same
        pass and no ``parent_source_guid``. Nothing to look up, everything to read."""
        row = {"source_guid": "MINTED", "content": {"source": {"url": "http://mine.com"}}}

        enriched, skipped = scope_pass([row], scope={"observe": ["source.url"]})

        assert skipped == []
        assert observed_urls(enriched) == ["http://mine.com"]

    def test_the_two_resolvers_agree_on_the_same_input(self):
        """The parity the issue is about. RECORD-mode returns the record itself, so the
        namespace it hands on is the carried one; FILE mode must observe that same one."""
        row = carrying("http://carried.com")

        record_mode = resolve_source_content(row, row["source_guid"], POOL, "test")
        enriched, _ = scope_pass([row])

        assert record_mode is not None
        assert record_mode["content"]["source"]["url"] == observed_urls(enriched)[0]


class TestTheFallbackDoesNotOutrankIdentity:
    """Additive means additive: only rows that would be skipped may change."""

    def test_a_row_whose_own_guid_resolves_still_takes_the_pool(self):
        enriched, skipped = scope_pass([carrying("http://carried.com", source_guid="ANCESTOR")])

        assert skipped == []
        assert observed_urls(enriched) == ["http://pool.com"]

    def test_a_row_resolving_through_its_parent_still_takes_the_pool(self):
        row = carrying("http://carried.com", parent_source_guid="OTHER")

        enriched, skipped = scope_pass([row])

        assert skipped == []
        assert observed_urls(enriched) == ["http://other.com"]


class TestRowsWithNothingToFallBackOnStillSkip:
    """The fallback must not become a blanket resolve — a genuine miss is still a miss."""

    def test_a_row_carrying_no_source_namespace_is_still_unresolved(self):
        enriched, skipped = scope_pass([{"source_guid": "GHOST", "content": {"a1": {"i": 1}}}])

        assert enriched == []
        assert skipped == [{"source_guid": "GHOST", "reason": "source_unresolved"}]

    def test_a_carried_source_that_is_not_a_namespace_is_not_used(self):
        """``source`` holding a scalar is malformed, not a namespace to read fields off."""
        row = {"source_guid": "GHOST", "content": {"source": "just a string", "a1": {"i": 1}}}

        enriched, skipped = scope_pass([row])

        assert enriched == []
        assert skipped == [{"source_guid": "GHOST", "reason": "source_unresolved"}]


class TestOneRowsCarriedSourceIsNeverServedToAnother:
    """The call site caches the pool lookup under ``(source_guid, parent_source_guid)``.
    The carried namespace is per-record content, so a fallback cached under that key
    hands the first row's document to every later row sharing it — two rows carrying no
    guid share ``(None, None)``, and the skip path proves such rows reach here."""

    def test_two_rows_that_share_a_cache_key_each_keep_their_own(self):
        rows = [
            {"content": {"source": {"url": "http://first.com"}, "a1": {"i": 1}}},
            {"content": {"source": {"url": "http://second.com"}, "a1": {"i": 2}}},
        ]

        enriched, skipped = scope_pass(rows)

        assert skipped == []
        assert observed_urls(enriched) == ["http://first.com", "http://second.com"]


class TestTheRecordSurvivesTheWholeScopePass:
    def test_a_batch_where_every_row_carries_its_own_leaves_nothing_skipped(self):
        """The failure the issue names: all rows skipped, then the action dies on a
        ``prefilter_by_guard`` length mismatch. No row may be lost here."""
        rows = [carrying(f"http://{i}.com", source_guid=f"MINTED-{i}") for i in range(3)]

        enriched, skipped = scope_pass(rows)

        assert skipped == []
        assert observed_urls(enriched) == ["http://0.com", "http://1.com", "http://2.com"]

    def test_a_carrying_row_and_a_bare_one_are_told_apart(self):
        bare = {"source_guid": "GHOST", "content": {"a1": {"i": 9}}}

        enriched, skipped = scope_pass([carrying("http://carried.com"), bare])

        assert observed_urls(enriched) == ["http://carried.com"]
        assert skipped == [{"source_guid": "GHOST", "reason": "source_unresolved"}]
