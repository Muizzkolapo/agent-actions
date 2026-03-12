"""Tests for LineageBuilder.add_unified_lineage() method."""

from agent_actions.utils.lineage.builder import LineageBuilder


class TestUnifiedLineageFirstStage:
    """Test unified lineage for first-stage (no parent_item)."""

    def test_no_parent_creates_single_node_lineage(self):
        """First-stage: parent_item=None → lineage=[node_id]."""
        obj = {"content": {"text": "data"}}
        node_id = "extract_abc123"

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item=None)

        assert result["node_id"] == "extract_abc123"
        assert result["lineage"] == ["extract_abc123"]
        assert "parent_target_id" not in result
        assert "root_target_id" not in result

    def test_no_parent_no_ancestry_chain(self):
        """First-stage: No parent → no ancestry chain fields."""
        obj = {"content": {"text": "data"}}
        node_id = "node_def456"

        result = LineageBuilder.add_unified_lineage(obj, node_id)

        assert "parent_target_id" not in result
        assert "root_target_id" not in result


class TestUnifiedLineageSubsequentStage:
    """Test unified lineage for subsequent-stage (with parent_item)."""

    def test_parent_with_lineage_appends_node_id(self):
        """Subsequent-stage: parent_item with lineage → appends node_id."""
        obj = {"content": {"text": "output"}}
        node_id = "transform_xyz789"
        parent_item = {
            "node_id": "extract_abc123",
            "lineage": ["extract_abc123"],
        }

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item)

        assert result["node_id"] == "transform_xyz789"
        assert result["lineage"] == ["extract_abc123", "transform_xyz789"]

    def test_parent_without_lineage_creates_single_node(self):
        """Parent item without lineage → creates single-node lineage."""
        obj = {"content": {"text": "output"}}
        node_id = "node_new123"
        parent_item = {"some": "data"}

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item)

        assert result["lineage"] == ["node_new123"]


class TestUnifiedLineageAncestryChain:
    """Test ancestry chain propagation."""

    def test_parent_target_id_propagation(self):
        """Ancestry chain: parent_target_id propagation."""
        obj = {"content": {"text": "output"}}
        node_id = "node_123"
        parent_item = {
            "target_id": "target-parent",
            "lineage": ["node-parent"],
        }

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item)

        assert result["parent_target_id"] == "target-parent"

    def test_root_target_id_propagation(self):
        """Ancestry chain: root_target_id propagation."""
        obj = {"content": {"text": "output"}}
        node_id = "node_456"
        parent_item = {
            "target_id": "target-parent",
            "root_target_id": "target-root",
            "lineage": ["node-root", "node-parent"],
        }

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item)

        assert result["parent_target_id"] == "target-parent"
        assert result["root_target_id"] == "target-root"

    def test_root_target_id_initialization(self):
        """Ancestry chain: root_target_id initialization from target_id."""
        obj = {"content": {"text": "output"}}
        node_id = "node_789"
        parent_item = {
            "target_id": "target-first",
            "lineage": ["node-first"],
        }

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item)

        # When no root_target_id exists, parent's target_id becomes root
        assert result["parent_target_id"] == "target-first"
        assert result["root_target_id"] == "target-first"

    def test_missing_target_id_in_parent(self):
        """Handles missing target_id in parent."""
        obj = {"content": {"text": "output"}}
        node_id = "node_abc"
        parent_item = {"lineage": ["node-parent"]}

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item)

        assert "parent_target_id" not in result
        assert "root_target_id" not in result


class TestUnifiedLineageObjectImmutability:
    """Test object immutability."""

    def test_returns_copy_not_mutating_original(self):
        """Object immutability (returns copy)."""
        obj = {"content": {"text": "original"}}
        original_id = id(obj)
        node_id = "node_123"

        result = LineageBuilder.add_unified_lineage(obj, node_id)

        # Result is a new object
        assert id(result) != original_id
        # Original is unchanged
        assert "node_id" not in obj
        assert "lineage" not in obj


class TestUnifiedLineageEdgeCases:
    """Test edge cases for unified lineage."""

    def test_empty_parent_item(self):
        """Handles empty parent_item dict."""
        obj = {"content": {"text": "output"}}
        node_id = "node_123"
        parent_item = {}

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item)

        assert result["node_id"] == "node_123"
        assert result["lineage"] == ["node_123"]

    def test_parent_with_invalid_lineage(self):
        """Handles parent with invalid lineage type."""
        obj = {"content": {"text": "output"}}
        node_id = "node_456"
        parent_item = {"lineage": "not-a-list"}

        result = LineageBuilder.add_unified_lineage(obj, node_id, parent_item)

        # Invalid lineage ignored, creates new single-node lineage
        assert result["lineage"] == ["node_456"]

    def test_nested_content_preserved(self):
        """Nested content structure preserved."""
        obj = {
            "content": {
                "text": "data",
                "nested": {"deep": {"value": 123}},
            }
        }
        node_id = "node_789"

        result = LineageBuilder.add_unified_lineage(obj, node_id)

        assert result["content"]["nested"]["deep"]["value"] == 123
