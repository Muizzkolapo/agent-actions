"""A repeated source_guid must not decide a record's ancestry by list position.

Three places index records by source_guid. Two of them (DataTransformer and
scope_application) take the FIRST on a repeat; the lineage index took the LAST, so a
record's `source` namespace could come from one row while its lineage came from another.

Flipping it to first-wins is not enough on its own: among parent records a repeated guid
is ordinary — correlation.py keys a versioned 1:1 id on (version_base_name, source_guid),
so two versioned actions over one source record produce two rows sharing a guid — and
either end of the list is the wrong ancestor for one of them. The correlation id is what
distinguishes the branches, and the index used to discard it.
"""

from agent_actions.processing.enrichment import LineageEnricher


def _parents() -> list[dict]:
    return [
        {
            "source_guid": "s1",
            "version_correlation_id": "assess:s1",
            "lineage": {"root_target_id": "assess_root"},
            "target_id": "assess_tid",
        },
        {
            "source_guid": "s1",
            "version_correlation_id": "review:s1",
            "lineage": {"root_target_id": "review_root"},
            "target_id": "review_tid",
        },
    ]


class TestTheAncestorMatchesTheItemsBranch:
    def test_each_item_gets_its_own_branch_not_a_position(self):
        candidates = LineageEnricher._candidates_by_source_guid(_parents())

        for correlation, expected_root in (
            ("assess:s1", "assess_root"),
            ("review:s1", "review_root"),
        ):
            item = {"source_guid": "s1", "version_correlation_id": correlation}
            chosen = LineageEnricher._with_parent_fallback(item, candidates)

            assert chosen["lineage"]["root_target_id"] == expected_root, (
                correlation,
                chosen["version_correlation_id"],
            )

    def test_neither_first_nor_last_is_right_for_both(self):
        """The property the old index could not have: two items, two different answers."""
        candidates = LineageEnricher._candidates_by_source_guid(_parents())

        roots = {
            LineageEnricher._with_parent_fallback(
                {"source_guid": "s1", "version_correlation_id": c}, candidates
            )["lineage"]["root_target_id"]
            for c in ("assess:s1", "review:s1")
        }

        assert roots == {"assess_root", "review_root"}, roots

    def test_an_item_with_no_correlation_takes_the_first(self):
        """Nothing to match on, so it agrees with the two source resolvers."""
        candidates = LineageEnricher._candidates_by_source_guid(_parents())
        chosen = LineageEnricher._with_parent_fallback({"source_guid": "s1"}, candidates)

        assert chosen["version_correlation_id"] == "assess:s1"

    def test_a_correlation_no_parent_carries_takes_the_first(self):
        candidates = LineageEnricher._candidates_by_source_guid(_parents())
        item = {"source_guid": "s1", "version_correlation_id": "nobody:s1"}

        assert (
            LineageEnricher._with_parent_fallback(item, candidates)["version_correlation_id"]
            == "assess:s1"
        )


class TestTheIndexAgreesWithTheSourceResolvers:
    def test_a_repeated_guid_resolves_to_the_first_record(self):
        """Was last-wins, so lineage and the source namespace could disagree."""
        index = LineageEnricher._index_by_source_guid(_parents())

        assert index["s1"]["version_correlation_id"] == "assess:s1"

    def test_it_matches_the_file_mode_source_index(self):
        """The whole point: three indexes, one tie-break."""
        from agent_actions.prompt.context.scope_application import _build_source_index

        records = [
            {"source_guid": "s1", "content": {"doc": {"which": "first"}}},
            {"source_guid": "s1", "content": {"doc": {"which": "second"}}},
        ]
        file_mode = _build_source_index(records)
        lineage = LineageEnricher._index_by_source_guid(records)

        assert lineage["s1"]["content"]["doc"]["which"] == "first"
        assert file_mode["s1"]["content"]["doc"]["which"] == "first"


class TestTheUnremarkableCasesAreUnchanged:
    def test_a_lineage_bearing_item_is_returned_as_is(self):
        item = {"source_guid": "s1", "lineage": {"root_target_id": "own"}, "target_id": "t"}
        candidates = LineageEnricher._candidates_by_source_guid(_parents())

        assert LineageEnricher._with_parent_fallback(item, candidates) is item

    def test_no_parents_returns_the_item(self):
        item = {"source_guid": "s1"}

        assert LineageEnricher._with_parent_fallback(item, None) is item

    def test_an_unmatched_guid_returns_the_item(self):
        candidates = LineageEnricher._candidates_by_source_guid(_parents())
        item = {"source_guid": "elsewhere"}

        assert LineageEnricher._with_parent_fallback(item, candidates) is item

    def test_an_empty_list_indexes_to_none(self):
        assert LineageEnricher._candidates_by_source_guid([]) is None
        assert LineageEnricher._index_by_source_guid([]) is None
