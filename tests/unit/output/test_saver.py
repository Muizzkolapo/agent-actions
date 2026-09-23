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

    def test_basic_init(self):
        saver = UnifiedSourceDataSaver(storage_backend=MagicMock())

        assert saver.enable_deduplication is True
        assert saver.storage_backend is not None

    def test_deduplication_disabled(self, tmp_path):
        saver = UnifiedSourceDataSaver(
            enable_deduplication=False,
            storage_backend=MagicMock(),
        )
        assert saver.enable_deduplication is False

    def test_no_backend(self, tmp_path):
        saver = UnifiedSourceDataSaver(
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
    def test_the_event_names_the_path_the_items_are_stored_under(self, mock_fire, tmp_path):
        """The items go to the store under the relative path, so that is what the
        event names — there is no file to point at."""
        saver = UnifiedSourceDataSaver(storage_backend=MagicMock())

        saver.save_source_items([{"x": 1}], "node_1/batch_001")

        saving_event = mock_fire.call_args_list[0][0][0]
        assert "node_1/batch_001" in saving_event.file_path
        assert not saving_event.file_path.endswith(".json")


# ---------------------------------------------------------------------------
# Event firing
# ---------------------------------------------------------------------------


class TestSaverEvents:
    """Tests for event firing during save."""

    @patch("agent_actions.output.saver.fire_event")
    def test_fires_saving_and_saved_events(self, mock_fire, tmp_path):
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
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
    def test_the_events_do_not_name_a_file_that_is_never_written(self, mock_fire, tmp_path):
        """Source items go to the store. Naming agent_io/source/<path>.json sends
        anyone reading the event, or the log line beside it, to a path that has
        never existed."""
        saver = UnifiedSourceDataSaver(storage_backend=MagicMock())

        saver.save_source_items([{"k": "v"}], "path")

        assert not (tmp_path / "agent_io" / "source").exists()
        for call in mock_fire.call_args_list:
            named = call[0][0].file_path
            assert "agent_io/source" not in named, f"event points at an unwritten file: {named}"

    @patch("agent_actions.output.saver.fire_event")
    def test_bytes_written_calculated_correctly(self, mock_fire, tmp_path):
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
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
            storage_backend=None,
        )
        with pytest.raises(ValueError, match="Storage backend not configured"):
            saver.save_source_items([{"x": 1}], "path")

    def test_error_message_names_the_path_that_could_not_be_stored(self, tmp_path):
        saver = UnifiedSourceDataSaver(
            storage_backend=None,
        )
        with pytest.raises(ValueError) as exc:
            saver.save_source_items([{"x": 1}], "node/batch")

        message = str(exc.value)
        assert "node/batch" in message
        assert ".json" not in message, f"error names a file that is never written: {message}"

    @patch("agent_actions.output.saver.fire_event")
    def test_backend_write_error_propagates(self, mock_fire, tmp_path):
        backend = MagicMock()
        backend.write_source.side_effect = RuntimeError("db locked")
        saver = UnifiedSourceDataSaver(
            storage_backend=backend,
        )
        with pytest.raises(RuntimeError, match="db locked"):
            saver.save_source_items([{"x": 1}], "path")

    @patch("agent_actions.output.saver.fire_event")
    def test_binary_data_does_not_crash(self, mock_fire, tmp_path):
        """Items containing bytes values must not crash json.dumps."""
        backend = MagicMock()
        saver = UnifiedSourceDataSaver(
            storage_backend=backend,
        )
        items = [{"key": b"binary data from UDF", "normal": "text"}]
        # Should not raise TypeError
        saver.save_source_items(items, "binary_path")
        backend.write_source.assert_called_once()
        saved_event = mock_fire.call_args_list[1][0][0]
        assert saved_event.bytes_written > 0

    @patch("agent_actions.output.saver.fire_event")
    def test_saving_event_fired_before_backend_error(self, mock_fire, tmp_path):
        """Even if backend raises, the 'saving' event should have been fired."""
        backend = MagicMock()
        backend.write_source.side_effect = RuntimeError("fail")
        saver = UnifiedSourceDataSaver(
            storage_backend=backend,
        )
        with pytest.raises(RuntimeError):
            saver.save_source_items([{"x": 1}], "path")

        # At least the saving event was fired
        assert mock_fire.call_count >= 1
        saving_event = mock_fire.call_args_list[0][0][0]
        assert saving_event.__class__.__name__ == "SourceDataSavingEvent"
