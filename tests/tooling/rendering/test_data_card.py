"""Tests for centralized data-card rendering — classify_record, render_card_markdown."""

from agent_actions.tooling.rendering.data_card import (
    IDENTITY_KEYS,
    METADATA_KEYS,
    classify_field,
    classify_record,
    render_card_markdown,
)

# ── classify_field ─────────────────────────────────────────────────────────


class TestClassifyField:
    def test_identity_keys(self):
        assert classify_field("source_guid") == "identity"
        assert classify_field("target_id") == "identity"

    def test_metadata_keys(self):
        for key in ("lineage", "node_id", "metadata", "parent_target_id",
                     "root_target_id", "chunk_info", "_recovery", "_unprocessed", "_file"):
            assert classify_field(key) == "metadata", f"{key} should be metadata"

    def test_identity_keys_are_also_metadata(self):
        """source_guid and target_id are in both IDENTITY_KEYS and METADATA_KEYS,
        but classify_field should return 'identity' (checked first)."""
        for key in IDENTITY_KEYS:
            assert key in METADATA_KEYS
            assert classify_field(key) == "identity"

    def test_content_keys(self):
        assert classify_field("title") == "content"
        assert classify_field("description") == "content"
        assert classify_field("price") == "content"
        assert classify_field("some_custom_field") == "content"


# ── classify_record ────────────────────────────────────────────────────────


class TestClassifyRecord:
    def test_empty_record(self):
        result = classify_record({})
        assert result == {"identity": [], "content": [], "metadata": []}

    def test_mixed_record(self):
        record = {
            "source_guid": "abc-123",
            "title": "My Book",
            "price": 19.99,
            "lineage": ["step1"],
            "node_id": "n1",
        }
        result = classify_record(record)
        assert len(result["identity"]) == 1
        assert result["identity"][0] == ("source_guid", "abc-123")
        assert len(result["content"]) == 2
        content_keys = [k for k, _ in result["content"]]
        assert "title" in content_keys
        assert "price" in content_keys
        assert len(result["metadata"]) == 2

    def test_all_metadata(self):
        record = {k: "v" for k in METADATA_KEYS if k not in IDENTITY_KEYS}
        result = classify_record(record)
        assert len(result["content"]) == 0
        assert len(result["identity"]) == 0
        assert len(result["metadata"]) == len(record)


# ── render_card_markdown ───────────────────────────────────────────────────


class TestRenderCardMarkdown:
    def test_simple_record(self):
        record = {
            "source_guid": "guid-1",
            "title": "Test",
            "author": "Jane",
        }
        md = render_card_markdown(record)
        assert "**Source Guid**: `guid-1`" in md
        assert "---" in md
        assert "**Title**: Test" in md
        assert "**Author**: Jane" in md

    def test_metadata_footer(self):
        record = {
            "title": "X",
            "lineage": ["a", "b"],
            "node_id": "n1",
        }
        md = render_card_markdown(record)
        assert "_metadata:" in md
        assert "lineage" in md
        assert "node_id" in md

    def test_empty_record(self):
        md = render_card_markdown({})
        # Should not crash; may produce minimal output
        assert isinstance(md, str)

    def test_max_fields_truncation(self):
        record = {f"field_{i}": f"value_{i}" for i in range(20)}
        md = render_card_markdown(record, max_fields=5)
        assert "more fields" in md

    def test_no_truncation_when_under_limit(self):
        record = {"a": 1, "b": 2, "c": 3}
        md = render_card_markdown(record, max_fields=10)
        assert "more fields" not in md

    def test_nested_object_compact(self):
        record = {"tags": ["a", "b"]}
        md = render_card_markdown(record)
        # Short JSON should be inline with backticks
        assert '`["a", "b"]`' in md

    def test_nested_object_expanded(self):
        record = {"data": {f"k{i}": f"v{i}" for i in range(20)}}
        md = render_card_markdown(record)
        assert "```json" in md

    def test_long_form_prose(self):
        long_text = "A" * 400
        record = {"reasoning": long_text}
        md = render_card_markdown(record)
        # Should be block-quoted and truncated
        assert ">" in md
        assert "\u2026" in md  # ellipsis for truncation at 300 chars

    def test_null_value(self):
        record = {"field": None}
        md = render_card_markdown(record)
        assert "_null_" in md

    def test_boolean_values(self):
        record = {"active": True, "deleted": False}
        md = render_card_markdown(record)
        assert "true" in md
        assert "false" in md

    def test_numeric_formatting(self):
        record = {"count": 1234567}
        md = render_card_markdown(record)
        assert "1,234,567" in md

    def test_string_truncation(self):
        record = {"bio": "x" * 200}
        md = render_card_markdown(record)
        # Default max_length for _format_value is 80 in content rendering
        assert "\u2026" in md

    def test_identity_separator(self):
        """Records with identity fields should have a --- separator."""
        record = {"source_guid": "g1", "title": "T"}
        md = render_card_markdown(record)
        lines = md.split("\n\n")
        assert "---" in lines

    def test_no_identity_no_separator(self):
        """Records without identity fields should not start with ---."""
        record = {"title": "T", "author": "A"}
        md = render_card_markdown(record)
        assert not md.startswith("---")

    def test_metadata_only_record(self):
        record = {"lineage": ["a"], "node_id": "n1"}
        md = render_card_markdown(record)
        assert "_metadata:" in md
        # No content separator before metadata when no content fields
        parts = md.split("---")
        assert len(parts) <= 2  # at most one separator
