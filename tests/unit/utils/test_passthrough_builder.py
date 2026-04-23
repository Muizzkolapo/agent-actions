"""Tests for PassthroughItemBuilder — unified passthrough item construction."""

from unittest.mock import patch

from agent_actions.utils.passthrough_builder import PassthroughItemBuilder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_TARGET_ID = "fixed-target-id"
FIXED_NODE_ID = "test_action_fixed-node-id"


def _patch_id_gen():
    """Patch IDGenerator to return deterministic IDs."""
    return patch.multiple(
        "agent_actions.utils.passthrough_builder.IDGenerator",
        generate_target_id=staticmethod(lambda: FIXED_TARGET_ID),
        generate_node_id=staticmethod(lambda action_name: f"{action_name}_fixed-node-id"),
    )


# ---------------------------------------------------------------------------
# _reason_to_legacy_flag (private helper)
# ---------------------------------------------------------------------------


class TestReasonToLegacyFlag:
    """Map reason strings to legacy metadata flag names."""

    def test_conditional_clause_failed(self):
        result = PassthroughItemBuilder._reason_to_legacy_flag("conditional_clause_failed")
        assert result == "skipped_by_conditional"

    def test_where_clause_not_matched(self):
        result = PassthroughItemBuilder._reason_to_legacy_flag("where_clause_not_matched")
        assert result == "skipped_by_where_clause"

    def test_unknown_reason_defaults_to_where_clause(self):
        result = PassthroughItemBuilder._reason_to_legacy_flag("some_unknown_reason")
        assert result == "skipped_by_where_clause"

    def test_empty_string_defaults(self):
        result = PassthroughItemBuilder._reason_to_legacy_flag("")
        assert result == "skipped_by_where_clause"


# ---------------------------------------------------------------------------
# build_item — batch mode (default)
# ---------------------------------------------------------------------------


class TestBuildItemBatchMode:
    """build_item with mode='batch' (the default)."""

    def test_basic_batch_item_structure(self):
        """Batch items have _unprocessed, metadata.agent_type, and a legacy flag."""
        row = {"content": {"text": "hello"}, "target_id": "tid-1", "source_guid": "sg-1"}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row,
                reason="where_clause_not_matched",
                action_name="test_action",
            )

        assert item["_unprocessed"] is True
        assert item["metadata"]["agent_type"] == "tombstone"
        assert item["metadata"]["skipped_by_where_clause"] is True
        # Batch mode should NOT have a 'reason' string in metadata
        assert "reason" not in item["metadata"]

    def test_target_id_from_row(self):
        """target_id is taken from the row when present."""
        row = {"target_id": "existing-tid"}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="a"
            )
        assert item["target_id"] == "existing-tid"

    def test_target_id_falls_back_to_custom_id(self):
        """When row has no target_id, custom_id is used."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row,
                reason="where_clause_not_matched",
                action_name="a",
                custom_id="custom-tid",
            )
        assert item["target_id"] == "custom-tid"

    def test_target_id_falls_back_to_generated(self):
        """When neither row target_id nor custom_id exist, IDGenerator is used."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="a"
            )
        assert item["target_id"] == FIXED_TARGET_ID

    def test_source_guid_from_param(self):
        """Explicit source_guid parameter takes precedence."""
        row = {"source_guid": "row-sg"}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row,
                reason="where_clause_not_matched",
                action_name="a",
                source_guid="override-sg",
            )
        assert item["source_guid"] == "override-sg"

    def test_source_guid_from_row(self):
        """source_guid falls back to the row's source_guid."""
        row = {"source_guid": "row-sg"}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="a"
            )
        assert item["source_guid"] == "row-sg"

    def test_source_guid_falls_back_to_target_id(self):
        """When no source_guid anywhere, it falls back to the resolved target_id."""
        row = {"target_id": "tid-fallback"}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="a"
            )
        assert item["source_guid"] == "tid-fallback"

    def test_content_extracted_from_row(self):
        """When row has a 'content' key, that value is used as content."""
        inner = {"text": "payload"}
        row = {"content": inner}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="a"
            )
        assert item["content"] == inner

    def test_namespaced_content_preserved(self):
        """Namespaced content is preserved in the tombstone item."""
        namespaced = {"action_a": {"field_a": "val_a"}, "action_b": {"field_b": "val_b"}}
        row = {"content": namespaced, "target_id": "tid-1", "source_guid": "sg-1"}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="action_c"
            )
        assert item["content"] == namespaced

    def test_content_defaults_to_empty_dict_when_missing(self):
        """When row has no 'content' key, content defaults to empty dict."""
        row = {"field1": "val1", "field2": "val2"}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="a"
            )
        assert item["content"] == {}

    def test_conditional_clause_flag_in_batch(self):
        """Batch mode with conditional_clause_failed sets the right flag."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="conditional_clause_failed", action_name="a"
            )
        assert item["metadata"]["skipped_by_conditional"] is True
        assert "reason" not in item["metadata"]

    def test_node_id_uses_action_name(self):
        """node_id is generated from the action_name."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="my_action"
            )
        assert item["node_id"] == "my_action_fixed-node-id"

    def test_lineage_contains_node_id(self):
        """The lineage list includes the generated node_id."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="my_action"
            )
        assert "my_action_fixed-node-id" in item["lineage"]

    def test_lineage_appends_to_existing(self):
        """When the row already has lineage, the new node_id is appended."""
        row = {"lineage": ["prev_action_abc-123"]}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="my_action"
            )
        assert item["lineage"] == ["prev_action_abc-123", "my_action_fixed-node-id"]


# ---------------------------------------------------------------------------
# build_item — online mode
# ---------------------------------------------------------------------------


class TestBuildItemOnlineMode:
    """build_item with mode='online' adds a reason string in metadata."""

    def test_online_has_reason_string(self):
        """Online mode adds metadata.reason as a string."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row,
                reason="where_clause_not_matched",
                action_name="a",
                mode="online",
            )
        assert item["metadata"]["reason"] == "where_clause_not_matched"

    def test_online_also_has_legacy_flag(self):
        """Online mode still sets the legacy boolean flag."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row,
                reason="where_clause_not_matched",
                action_name="a",
                mode="online",
            )
        assert item["metadata"]["skipped_by_where_clause"] is True

    def test_online_conditional_reason(self):
        """Online mode with conditional_clause_failed reason."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row,
                reason="conditional_clause_failed",
                action_name="a",
                mode="online",
            )
        assert item["metadata"]["reason"] == "conditional_clause_failed"
        assert item["metadata"]["skipped_by_conditional"] is True

    def test_online_tombstone_marker(self):
        """Online items still have agent_type=tombstone and _unprocessed."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row,
                reason="where_clause_not_matched",
                action_name="a",
                mode="online",
            )
        assert item["_unprocessed"] is True
        assert item["metadata"]["agent_type"] == "tombstone"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestBuildItemEdgeCases:
    """Edge cases: empty rows, falsy target_ids, etc."""

    def test_empty_row(self):
        """An empty row still produces a valid passthrough item with empty content."""
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row={}, reason="where_clause_not_matched", action_name="a"
            )
        assert item["_unprocessed"] is True
        assert item["metadata"]["agent_type"] == "tombstone"
        assert item["target_id"] == FIXED_TARGET_ID
        assert item["content"] == {}

    def test_falsy_target_id_in_row(self):
        """A falsy (empty string) target_id in the row is treated as missing."""
        row = {"target_id": ""}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="a"
            )
        # Empty string is falsy, so should fall back to generated ID
        assert item["target_id"] == FIXED_TARGET_ID

    def test_none_target_id_in_row(self):
        """A None target_id in the row is treated as missing."""
        row = {"target_id": None}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row,
                reason="where_clause_not_matched",
                action_name="a",
                custom_id="custom-fallback",
            )
        assert item["target_id"] == "custom-fallback"

    def test_unknown_reason_in_batch(self):
        """Unknown reason still produces a valid item with the default flag."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="totally_new_reason", action_name="a"
            )
        assert item["metadata"]["skipped_by_where_clause"] is True

    def test_unknown_reason_in_online(self):
        """Online mode with unknown reason still stores the raw reason string."""
        row = {}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="totally_new_reason", action_name="a", mode="online"
            )
        assert item["metadata"]["reason"] == "totally_new_reason"
        assert item["metadata"]["skipped_by_where_clause"] is True

    def test_row_with_existing_lineage_invalid_entries(self):
        """Invalid lineage entries in the row are filtered out."""
        row = {"lineage": ["valid_action_abc-123", "not valid!", 42]}
        with _patch_id_gen():
            item = PassthroughItemBuilder.build_item(
                row=row, reason="where_clause_not_matched", action_name="my_action"
            )
        # Only valid node IDs survive the filter, plus the new one
        assert item["lineage"] == ["valid_action_abc-123", "my_action_fixed-node-id"]
