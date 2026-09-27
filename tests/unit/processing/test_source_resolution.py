"""Tests for shared source content resolution."""

import pytest

from agent_actions.processing.source_resolution import (
    resolve_first_stage_source,
    resolve_source_content,
)


class TestResolveSourceContent:
    """Tests for resolve_source_content()."""

    def test_returns_item_for_a_carried_namespace_when_there_is_no_pool(self):
        """With no pool there is no identity to read first, so the namespace the
        record carries is the answer."""
        item = {"content": {"source": {"field": "val"}}, "source_guid": "sg"}
        result = resolve_source_content(item, "sg", None)
        assert result is item

    def test_guid_lookup_resolves_first(self):
        """The guid lookup is the first step, not a fallback for a record with no
        source key — this record happens to have none, which is incidental."""
        item = {"content": {"upstream": {"x": 1}}, "source_guid": "sg-123"}
        source_data = [{"source_guid": "sg-123", "content": {"source": {"a": 1}}}]
        result = resolve_source_content(item, "sg-123", source_data)
        assert result == {"source_guid": "sg-123", "content": {"source": {"a": 1}}}

    def test_no_guid_and_no_pool_returns_none(self):
        """No source_guid, no pool -> None (no identity to resolve, nothing to substitute)."""
        item = {"content": {"upstream": {"x": 1}}}
        result = resolve_source_content(item, None, None)
        assert result is None

    def test_guid_not_found_in_pool_returns_none(self):
        """Guid exists but misses a non-empty pool -> None, never the item's own content.

        Returning `item` here would expose the record's OWN unrelated action
        namespaces (e.g. its own prior-stage output) as if they were the
        source document — the same silent-misattribution shape as #866, just
        with the record's own data standing in for a stranger's.
        """
        item = {"content": {"upstream": {"x": 1}}, "source_guid": "sg-miss"}
        source_data = [{"source_guid": "sg-other", "content": {"source": {"a": 1}}}]
        result = resolve_source_content(item, "sg-miss", source_data)
        assert result is None

    def test_resolves_via_parent_source_guid_when_own_guid_misses(self):
        """Expansion descendants resolve through their carried attribution."""
        item = {
            "content": {"upstream": {"x": 1}},
            "source_guid": "minted-child",
            "parent_source_guid": "sg-123",
        }
        source_data = [{"source_guid": "sg-123", "content": {"source": {"a": 1}}}]
        result = resolve_source_content(item, "minted-child", source_data)
        assert result == {"source_guid": "sg-123", "content": {"source": {"a": 1}}}

    def test_own_guid_wins_over_parent_source_guid(self):
        """A record whose own guid resolves never falls through to its parent's."""
        item = {
            "content": {"upstream": {"x": 1}},
            "source_guid": "sg-2",
            "parent_source_guid": "sg-1",
        }
        source_data = [
            {"source_guid": "sg-1", "content": {"source": {"a": "one"}}},
            {"source_guid": "sg-2", "content": {"source": {"a": "two"}}},
        ]
        result = resolve_source_content(item, "sg-2", source_data)
        assert result == {"source_guid": "sg-2", "content": {"source": {"a": "two"}}}

    def test_both_guid_and_parent_miss_returns_none(self):
        """Neither hop resolves against a non-empty pool -> None, not the item."""
        item = {
            "content": {"upstream": {"x": 1}},
            "source_guid": "minted-child",
            "parent_source_guid": "also-unknown",
        }
        source_data = [{"source_guid": "sg-other", "content": {"source": {"a": 1}}}]
        result = resolve_source_content(item, "minted-child", source_data)
        assert result is None

    def test_non_dict_content_returns_none_when_pool_present(self):
        """Non-dict content, guid misses a non-empty pool -> None."""
        item = {"content": "string", "source_guid": "sg-miss"}
        source_data = [{"source_guid": "sg-other", "content": {"source": {"a": 1}}}]
        result = resolve_source_content(item, "sg-miss", source_data)
        assert result is None

    def test_empty_item_and_no_pool_returns_none(self):
        """Empty dict, no pool -> None."""
        item: dict = {}
        result = resolve_source_content(item, None, None)
        assert result is None


class TestResolveFirstStageSource:
    """A first-stage record IS the input, so its own content is the source document."""

    def test_a_record_comes_back_enveloped(self):
        """The namespace builder reads an envelope; handed the inner dict it publishes
        the namespace one level too deep."""
        assert resolve_first_stage_source({"title": "T", "source_guid": "G"}) == {
            "content": {"source": {"title": "T"}}
        }

    def test_the_framework_keys_of_a_flat_record_are_not_document_fields(self):
        row = {"title": "T", "source_guid": "G", "node_id": "n", "lineage": ["a0"]}

        assert resolve_first_stage_source(row) == {"content": {"source": {"title": "T"}}}

    def test_an_enveloped_record_keeps_the_document_it_carries(self):
        """Its user fields already sit under content.source, including one that shares a
        framework name — the envelope is what makes that safe."""
        row = {"content": {"source": {"lineage": "user value"}}, "source_guid": "G"}

        assert resolve_first_stage_source(row) == {"content": {"source": {"lineage": "user value"}}}

    @pytest.mark.parametrize("item", ["just some text", [{"title": "T"}], 7, 0.5, True])
    def test_a_non_record_item_is_returned_unchanged(self, item):
        """``_normalize_input`` returns the item unchanged at first stage whatever its
        type, so normalizing one unconditionally raises AttributeError on .get."""
        assert resolve_first_stage_source(item) is item
