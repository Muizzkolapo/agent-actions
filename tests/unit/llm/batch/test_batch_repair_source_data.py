"""Tests for repair batch source data resolution.

Covers _load_source_data and source_data forwarding to prepare_tasks.
"""

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# _load_source_data
# ---------------------------------------------------------------------------


def _included_row() -> dict:
    """A preparation context_map entry for a record that was admitted."""
    from agent_actions.llm.batch.core.batch_constants import FilterStatus
    from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

    row: dict = {}
    BatchContextMetadata.set_filter_status(row, FilterStatus.INCLUDED)
    return row


class TestLoadSourceDataForReprompt:
    """_load_source_data loads source records from the storage backend."""

    def test_returns_records_from_storage_backend(self):
        from agent_actions.llm.batch.services.repair_ops import _load_source_data

        backend = MagicMock()
        backend.list_source_files.return_value = ["staging/workflow_a"]
        backend.read_source.return_value = [
            {"source_guid": "g1", "page_content": "hello"},
            {"source_guid": "g2", "page_content": "world"},
        ]

        result = _load_source_data(backend)

        assert result is not None
        assert len(result) == 2
        assert result[0]["page_content"] == "hello"
        backend.read_source.assert_called_once_with("staging/workflow_a")

    def test_merges_multiple_source_files(self):
        from agent_actions.llm.batch.services.repair_ops import _load_source_data

        backend = MagicMock()
        backend.list_source_files.return_value = ["staging/a", "staging/b"]
        backend.read_source.side_effect = [
            [{"source_guid": "g1"}],
            [{"source_guid": "g2"}],
        ]

        result = _load_source_data(backend)

        assert result is not None
        assert len(result) == 2

    def test_returns_none_when_backend_is_none(self):
        from agent_actions.llm.batch.services.repair_ops import _load_source_data

        assert _load_source_data(None) is None

    def test_returns_none_when_no_source_files(self):
        from agent_actions.llm.batch.services.repair_ops import _load_source_data

        backend = MagicMock()
        backend.list_source_files.return_value = []

        assert _load_source_data(backend) is None

    def test_skips_missing_source_files(self):
        from agent_actions.llm.batch.services.repair_ops import _load_source_data

        backend = MagicMock()
        backend.list_source_files.return_value = ["missing", "exists"]
        backend.read_source.side_effect = [
            FileNotFoundError("gone"),
            [{"source_guid": "g1"}],
        ]

        result = _load_source_data(backend)

        assert result is not None
        assert len(result) == 1

    def test_returns_none_on_unexpected_error(self):
        from agent_actions.llm.batch.services.repair_ops import _load_source_data

        backend = MagicMock()
        backend.list_source_files.side_effect = RuntimeError("boom")

        assert _load_source_data(backend) is None


# ---------------------------------------------------------------------------
# source_data forwarded to prepare_tasks in both reprompt paths
# ---------------------------------------------------------------------------
