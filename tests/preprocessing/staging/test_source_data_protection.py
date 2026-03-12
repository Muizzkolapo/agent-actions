"""
Tests for source data protection (_should_save_source_items).

Tests the richness comparison logic that prevents sparse downstream outputs
from overwriting rich initial source data.
"""

import json
import tempfile
from pathlib import Path

import pytest

from agent_actions.input.preprocessing.staging.initial_pipeline import _should_save_source_items


class TestShouldSaveSourceItems:
    """Test _should_save_source_items() richness comparison logic."""

    def test_nonexistent_source_file_returns_true(self):
        """Test that missing source file allows save (first run)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            file_path = base_dir / "input" / "test.json"

            new_items = [{"source_guid": "guid-1", "field": "value"}]

            result = _should_save_source_items(new_items, str(file_path), str(base_dir), None)

            assert result is True

    def test_empty_existing_file_returns_true(self):
        """Test that empty existing file allows save."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup: Create workflow structure with empty source file
            workflow_root = Path(tmpdir) / "workflow"
            source_dir = workflow_root / "agent_io" / "source" / "input"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "test.json"
            source_file.write_text("[]")  # Empty list

            base_dir = workflow_root / "agent_io" / "staging" / "input"
            base_dir.mkdir(parents=True)
            file_path = base_dir / "test.json"

            new_items = [{"source_guid": "guid-1", "field": "value"}]

            result = _should_save_source_items(new_items, str(file_path), str(base_dir), None)

            assert result is True

    def test_richer_new_data_returns_true(self):
        """Test that new data with MORE fields is allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup: Create workflow structure with sparse source file
            workflow_root = Path(tmpdir) / "workflow"
            source_dir = workflow_root / "agent_io" / "source" / "input"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "test.json"

            existing_data = [{"source_guid": "guid-1", "id": "123"}]  # 2 fields
            source_file.write_text(json.dumps(existing_data))

            base_dir = workflow_root / "agent_io" / "staging" / "input"
            base_dir.mkdir(parents=True)
            file_path = base_dir / "test.json"

            # New data with MORE fields (richer)
            new_items = [
                {
                    "source_guid": "guid-1",
                    "id": "123",
                    "page_content": "Full text",  # Additional field
                    "title": "My Title",  # Additional field
                }
            ]  # 4 fields

            result = _should_save_source_items(new_items, str(file_path), str(base_dir), None)

            assert result is True  # Allow richer data to save

    def test_sparse_new_data_returns_false(self):
        """Test that new data with FEWER fields is blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup: Create workflow structure with rich source file
            workflow_root = Path(tmpdir) / "workflow"

            # Create the source file at: workflow/agent_io/source/test.json
            source_file = workflow_root / "agent_io" / "source" / "test.json"
            source_file.parent.mkdir(parents=True)

            existing_data = [
                {
                    "source_guid": "guid-1",
                    "id": "123",
                    "page_content": "Full text",
                    "title": "My Title",
                    "url": "http://example.com",
                }
            ]  # 5 fields
            source_file.write_text(json.dumps(existing_data))

            # file_path and base_directory for function call
            # base_directory must contain agent_io for path resolution to work
            base_dir = workflow_root / "agent_io" / "staging"
            base_dir.mkdir(parents=True, exist_ok=True)
            file_path = base_dir / "test.json"

            # New data with FEWER fields (sparse)
            new_items = [{"source_guid": "guid-1", "id": "123"}]  # 2 fields

            result = _should_save_source_items(new_items, str(file_path), str(base_dir), None)

            assert result is False  # Block sparse data from overwriting

    def test_invalid_json_in_existing_file_returns_true(self):
        """Test that corrupted existing file allows save (recovery)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup: Create workflow structure with invalid JSON
            workflow_root = Path(tmpdir) / "workflow"
            source_dir = workflow_root / "agent_io" / "source" / "input"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "test.json"
            source_file.write_text("invalid json{")  # Corrupted

            base_dir = workflow_root / "agent_io" / "staging" / "input"
            base_dir.mkdir(parents=True)
            file_path = base_dir / "test.json"

            new_items = [{"source_guid": "guid-1", "field": "value"}]

            result = _should_save_source_items(new_items, str(file_path), str(base_dir), None)

            assert result is True  # Allow recovery

    def test_with_output_directory_parameter(self):
        """Test that output_directory parameter is used for path resolution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup: Create workflow structure
            workflow_root = Path(tmpdir) / "workflow"
            source_dir = workflow_root / "agent_io" / "source" / "input"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "test.json"

            existing_data = [{"source_guid": "guid-1", "id": "123"}]  # 2 fields
            source_file.write_text(json.dumps(existing_data))

            # Use output_directory for path resolution
            output_dir = workflow_root / "agent_io" / "target" / "node_1" / "input"
            output_dir.mkdir(parents=True)

            base_dir = workflow_root / "agent_io" / "staging" / "input"
            base_dir.mkdir(parents=True)
            file_path = base_dir / "test.json"

            new_items = [{"source_guid": "guid-1", "id": "123", "extra": "field"}]  # 3 fields

            result = _should_save_source_items(
                new_items, str(file_path), str(base_dir), str(output_dir)
            )

            assert result is True  # Richer data allowed

    def test_real_world_scenario_sparse_overwrite_blocked(self):
        """Test real-world scenario: downstream sparse output blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup: Initial rich source data
            workflow_root = Path(tmpdir) / "workflow"
            source_dir = workflow_root / "agent_io" / "source"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "combined_scraped.json"

            # Rich initial data (10 fields)
            initial_rich_data = [
                {
                    "id": "d947c7e0-1060-4064-831d-2e83b71e2c68",
                    "url": "https://example.com",
                    "title": "My Document",
                    "source": "document.md",
                    "page_content": "Full page content here...",
                    "referenced_in": [{"section": "intro"}],
                    "source_guid": "479ad63d-31d7-5548-9e26-9f45b6226923",
                    "metadata": {"author": "John"},
                    "tags": ["important"],
                    "created_at": "2024-01-01",
                }
            ]
            source_file.write_text(json.dumps(initial_rich_data))

            # Downstream action tries to save sparse output (only 2 fields)
            base_dir = source_dir
            file_path = source_file

            sparse_output = [
                {"source_guid": "479ad63d-31d7-5548-9e26-9f45b6226923", "id": "filtered-123"}
            ]

            result = _should_save_source_items(sparse_output, str(file_path), str(base_dir), None)

            # Should BLOCK sparse overwrite
            assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
