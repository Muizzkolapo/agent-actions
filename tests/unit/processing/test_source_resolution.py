"""Tests for shared source content resolution."""

from agent_actions.processing.source_resolution import resolve_source_content


class TestResolveSourceContent:
    """Tests for resolve_source_content()."""

    def test_returns_item_when_source_in_content(self):
        """Tier 1: record content has 'source' key -> return record."""
        item = {"content": {"source": {"field": "val"}}, "source_guid": "sg"}
        result = resolve_source_content(item, "sg", None)
        assert result is item

    def test_guid_lookup_when_no_source_key(self):
        """Tier 2: source_guid + source_data -> look up by guid."""
        item = {"content": {"upstream": {"x": 1}}, "source_guid": "sg-123"}
        source_data = [{"source_guid": "sg-123", "content": {"source": {"a": 1}}}]
        result = resolve_source_content(item, "sg-123", source_data)
        assert result == {"source_guid": "sg-123", "content": {"source": {"a": 1}}}

    def test_falls_back_to_item_when_no_guid(self):
        """Tier 3: no source_guid -> fall back to item."""
        item = {"content": {"upstream": {"x": 1}}}
        result = resolve_source_content(item, None, None)
        assert result is item

    def test_falls_back_to_item_when_guid_not_found(self):
        """Tier 3: guid exists but not in source_data -> fall back to item."""
        item = {"content": {"upstream": {"x": 1}}, "source_guid": "sg-miss"}
        source_data = [{"source_guid": "sg-other", "content": {"source": {"a": 1}}}]
        result = resolve_source_content(item, "sg-miss", source_data)
        assert result is item

    def test_non_dict_content_falls_back(self):
        """Non-dict content -> fall back to item."""
        item = {"content": "string"}
        result = resolve_source_content(item, None, None)
        assert result is item

    def test_empty_item_falls_back(self):
        """Empty dict -> fall back to item."""
        item: dict = {}
        result = resolve_source_content(item, None, None)
        assert result is item
