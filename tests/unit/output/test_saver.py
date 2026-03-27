"""Tests for UnifiedSourceDataSaver."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.output.saver import UnifiedSourceDataSaver

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSaverInit:
    """Tests for UnifiedSourceDataSaver initialization."""

    def test_basic_init(self, tmp_path):
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=MagicMock(),
        )
        assert saver.base_directory == tmp_path
        assert saver.enable_deduplication is True
        assert saver.storage_backend is not None

    def test_deduplication_disabled(self, tmp_path):
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            enable_deduplication=False,
            storage_backend=MagicMock(),
        )
        assert saver.enable_deduplication is False

    def test_no_backend(self, tmp_path):
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=None,
        )
        assert saver.storage_backend is None


# ---------------------------------------------------------------------------
# save_source_items — happy path
# ---------------------------------------------------------------------------


class TestSaveSourceItems:
    """Tests for save_source_items."""

    @patch("agent_actions.output.saver.fire_event")
    def test_single_dict_wrapped_to_list(self, mock_fire, tmp_path):
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=backend,
        )
        item = {"key": "value"}
        saver.save_source_items(item, "node_1/batch_001")

        backend.write_source.assert_called_once_with(
            "node_1/batch_001",
            [item],
            enable_deduplication=True,
        )

    @patch("agent_actions.output.saver.fire_event")
    def test_list_of_dicts_passed_through(self, mock_fire, tmp_path):
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=backend,
        )
        items = [{"a": 1}, {"b": 2}]
        saver.save_source_items(items, "node_1/batch_001")

        backend.write_source.assert_called_once_with(
            "node_1/batch_001",
            items,
            enable_deduplication=True,
        )

    @patch("agent_actions.output.saver.fire_event")
    def test_deduplication_flag_forwarded(self, mock_fire, tmp_path):
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            enable_deduplication=False,
            storage_backend=backend,
        )
        saver.save_source_items([{"x": 1}], "rel")

        backend.write_source.assert_called_once_with(
            "rel",
            [{"x": 1}],
            enable_deduplication=False,
        )

    @patch("agent_actions.output.saver.fire_event")
    def test_source_file_path_construction(self, mock_fire, tmp_path):
        """Source file path should be base/agent_io/source/{relative_path}.json."""
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=backend,
        )
        saver.save_source_items([{"x": 1}], "node_1/batch_001")

        expected_path = str(tmp_path / "agent_io" / "source" / "node_1" / "batch_001.json")
        # Verify the saving event received the correct path
        saving_event = mock_fire.call_args_list[0][0][0]
        assert saving_event.file_path == expected_path


# ---------------------------------------------------------------------------
# Event firing
# ---------------------------------------------------------------------------


class TestSaverEvents:
    """Tests for event firing during save."""

    @patch("agent_actions.output.saver.fire_event")
    def test_fires_saving_and_saved_events(self, mock_fire, tmp_path):
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=backend,
        )
        items = [{"k": "v"}]
        saver.save_source_items(items, "path")

        assert mock_fire.call_count == 2

        # First call: SourceDataSavingEvent
        saving_event = mock_fire.call_args_list[0][0][0]
        assert saving_event.__class__.__name__ == "SourceDataSavingEvent"
        assert saving_event.item_count == 1

        # Second call: SourceDataSavedEvent
        saved_event = mock_fire.call_args_list[1][0][0]
        assert saved_event.__class__.__name__ == "SourceDataSavedEvent"
        assert saved_event.item_count == 1
        assert saved_event.bytes_written == len(json.dumps({"k": "v"}).encode())

    @patch("agent_actions.output.saver.fire_event")
    def test_bytes_written_calculated_correctly(self, mock_fire, tmp_path):
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=backend,
        )
        items = [{"a": 1}, {"b": "hello"}]
        saver.save_source_items(items, "p")

        saved_event = mock_fire.call_args_list[1][0][0]
        expected_bytes = sum(len(json.dumps(item).encode()) for item in items)
        assert saved_event.bytes_written == expected_bytes


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestSaverErrors:
    """Tests for error handling in save_source_items."""

    def test_raises_valueerror_when_no_backend(self, tmp_path):
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=None,
        )
        with pytest.raises(ValueError, match="Storage backend not configured"):
            saver.save_source_items([{"x": 1}], "path")

    def test_error_message_includes_file_path(self, tmp_path):
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=None,
        )
        with pytest.raises(ValueError, match=r"\.json"):
            saver.save_source_items([{"x": 1}], "node/batch")

    @patch("agent_actions.output.saver.fire_event")
    def test_backend_write_error_propagates(self, mock_fire, tmp_path):
        backend = MagicMock()
        backend.write_source.side_effect = RuntimeError("db locked")
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=backend,
        )
        with pytest.raises(RuntimeError, match="db locked"):
            saver.save_source_items([{"x": 1}], "path")

    @patch("agent_actions.output.saver.fire_event")
    def test_saving_event_fired_before_backend_error(self, mock_fire, tmp_path):
        """Even if backend raises, the 'saving' event should have been fired."""
        backend = MagicMock()
        backend.write_source.side_effect = RuntimeError("fail")
        saver = UnifiedSourceDataSaver(
            base_directory=str(tmp_path),
            storage_backend=backend,
        )
        with pytest.raises(RuntimeError):
            saver.save_source_items([{"x": 1}], "path")

        # At least the saving event was fired
        assert mock_fire.call_count >= 1
        saving_event = mock_fire.call_args_list[0][0][0]
        assert saving_event.__class__.__name__ == "SourceDataSavingEvent"
