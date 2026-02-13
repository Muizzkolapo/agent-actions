"""Tests for per-record disposition writes in BatchProcessingService."""

from unittest.mock import MagicMock

from agent_actions.llm.batch.services.processing import BatchProcessingService


def _make_service(storage_backend=None, action_name=None):
    """Create a BatchProcessingService with mocked dependencies."""
    return BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        storage_backend=storage_backend,
        action_name=action_name,
    )


class TestBatchWriteRecordDispositions:
    """Tests for _write_record_dispositions."""

    def _make_backend(self):
        backend = MagicMock()
        backend.set_disposition = MagicMock()
        return backend

    def test_exhausted_item_writes_disposition(self):
        backend = self._make_backend()
        service = _make_service(storage_backend=backend, action_name="extract")

        items = [
            {
                "source_guid": "guid-1",
                "metadata": {"retry_exhausted": True},
                "content": {},
            }
        ]

        service._write_record_dispositions(items, "extract")

        backend.set_disposition.assert_called_once_with(
            "extract",
            "guid-1",
            "exhausted",
            reason="retry_exhausted",
        )

    def test_unprocessed_skipped_item_writes_skipped(self):
        backend = self._make_backend()
        service = _make_service(storage_backend=backend, action_name="classify")

        items = [
            {
                "source_guid": "guid-2",
                "_unprocessed": True,
                "metadata": {"reason": "not_applicable"},
                "content": {},
            }
        ]

        service._write_record_dispositions(items, "classify")

        backend.set_disposition.assert_called_once_with(
            "classify",
            "guid-2",
            "skipped",
            reason="not_applicable",
        )

    def test_where_clause_filtered_writes_filtered(self):
        backend = self._make_backend()
        service = _make_service(storage_backend=backend, action_name="classify")

        items = [
            {
                "source_guid": "guid-3",
                "_unprocessed": True,
                "metadata": {
                    "reason": "WHERE clause filtered",
                    "skipped_by_where_clause": True,
                },
                "content": {},
            }
        ]

        service._write_record_dispositions(items, "classify")

        backend.set_disposition.assert_called_once_with(
            "classify",
            "guid-3",
            "filtered",
            reason="WHERE clause filtered",
        )

    def test_error_item_writes_failed(self):
        backend = self._make_backend()
        service = _make_service(storage_backend=backend, action_name="extract")

        items = [
            {
                "source_guid": "guid-4",
                "error": "API timeout after 30s",
                "metadata": {},
                "content": {},
            }
        ]

        service._write_record_dispositions(items, "extract")

        backend.set_disposition.assert_called_once_with(
            "extract",
            "guid-4",
            "failed",
            reason="API timeout after 30s",
        )

    def test_error_reason_truncated_to_500_chars(self):
        backend = self._make_backend()
        service = _make_service(storage_backend=backend, action_name="extract")

        long_error = "x" * 1000
        items = [
            {
                "source_guid": "guid-5",
                "error": long_error,
                "metadata": {},
            }
        ]

        service._write_record_dispositions(items, "extract")

        call_reason = backend.set_disposition.call_args[1]["reason"]
        assert len(call_reason) == 500

    def test_success_item_no_disposition(self):
        """Normal success items (no error markers) should not get dispositions."""
        backend = self._make_backend()
        service = _make_service(storage_backend=backend, action_name="extract")

        items = [
            {
                "source_guid": "guid-ok",
                "metadata": {},
                "content": {"value": 42},
            }
        ]

        service._write_record_dispositions(items, "extract")

        backend.set_disposition.assert_not_called()

    def test_missing_source_guid_skipped(self):
        """Items without source_guid should be skipped entirely."""
        backend = self._make_backend()
        service = _make_service(storage_backend=backend, action_name="extract")

        items = [
            {"metadata": {"retry_exhausted": True}, "content": {}},
        ]

        service._write_record_dispositions(items, "extract")

        backend.set_disposition.assert_not_called()

    def test_mixed_items_write_correct_dispositions(self):
        """Multiple items with different statuses write correct dispositions."""
        backend = self._make_backend()
        service = _make_service(storage_backend=backend, action_name="agent")

        items = [
            {"source_guid": "ok", "metadata": {}, "content": {"v": 1}},
            {"source_guid": "ex", "metadata": {"retry_exhausted": True}, "content": {}},
            {"source_guid": "err", "error": "boom", "metadata": {}, "content": {}},
        ]

        service._write_record_dispositions(items, "agent")

        assert backend.set_disposition.call_count == 2
        calls = backend.set_disposition.call_args_list
        assert calls[0] == (("agent", "ex", "exhausted"), {"reason": "retry_exhausted"})
        assert calls[1] == (("agent", "err", "failed"), {"reason": "boom"})
