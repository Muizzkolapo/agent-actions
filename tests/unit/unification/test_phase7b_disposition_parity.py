"""Phase 7b: Batch retrieve dispositions must match online collector rules.

U-3.2a: write_record_dispositions must produce the same disposition types,
reasons, and auxiliary fields (input_snapshot, detail) as ResultCollector.
collect_results() does for equivalent records.

U-3.5a: Prompt trace responses must only be written for SUCCESS records,
not for tombstones/passthroughs.
"""

import json
from typing import Any
from unittest.mock import MagicMock

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.processing.result_collector import write_record_dispositions
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import (
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_SUCCESS,
)


def _make_storage_backend() -> MagicMock:
    """Create a mock storage backend that tracks disposition calls."""
    backend = MagicMock()
    backend.set_disposition = MagicMock()
    backend.clear_disposition = MagicMock()
    return backend


class TestSuccessDisposition:
    """U-3.2a: SUCCESS records must get DISPOSITION_SUCCESS like online."""

    def test_success_record_gets_success_disposition(self):
        """Batch SUCCESS record (_state=processed) must write DISPOSITION_SUCCESS."""
        backend = _make_storage_backend()

        items = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "_state": RecordState.PROCESSED.value,
                "content": {"result": "LLM output"},
                "metadata": {},
            },
        ]

        write_record_dispositions(backend, items, "test_action")

        # Verify DISPOSITION_SUCCESS was written
        success_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if _get_disposition_arg(c) == DISPOSITION_SUCCESS
        ]
        assert len(success_calls) == 1, (
            f"Expected 1 SUCCESS disposition write, got {len(success_calls)}. "
            f"All calls: {backend.set_disposition.call_args_list}"
        )
        assert _get_record_id_arg(success_calls[0]) == "sg-001"

    def test_multiple_success_records(self):
        """Each SUCCESS record gets its own DISPOSITION_SUCCESS write."""
        backend = _make_storage_backend()

        items = [
            {
                "source_guid": "sg-001",
                "_state": RecordState.PROCESSED.value,
                "content": {"result": "output 1"},
                "metadata": {},
            },
            {
                "source_guid": "sg-002",
                "_state": RecordState.PROCESSED.value,
                "content": {"result": "output 2"},
                "metadata": {},
            },
        ]

        write_record_dispositions(backend, items, "test_action")

        success_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if _get_disposition_arg(c) == DISPOSITION_SUCCESS
        ]
        stamped_ids = {_get_record_id_arg(c) for c in success_calls}
        assert stamped_ids == {"sg-001", "sg-002"}


class TestFilteredDisposition:
    """U-3.2a: FILTERED records must get DISPOSITION_FILTERED like online."""

    def test_filtered_record_gets_filtered_disposition(self):
        """Records filtered during batch prep must receive DISPOSITION_FILTERED.

        The online path writes DISPOSITION_FILTERED for ProcessingStatus.FILTERED.
        The batch path must do the same for records with FilterStatus.FILTERED
        in the context_map.
        """
        backend = _make_storage_backend()

        # Simulate the processing service calling write_filtered_dispositions
        # (FILTERED records are excluded from workflow output items, so they
        # must be handled separately from write_record_dispositions).
        service = _build_processing_service(storage_backend=backend)

        context_map: dict[str, Any] = {}
        filtered_entry = {"source_guid": "sg-filtered", "content": {"text": "data"}}
        BatchContextMetadata.set_filter_status(filtered_entry, FilterStatus.FILTERED)
        BatchContextMetadata.set_skip_reason(filtered_entry, "guard_filter")
        context_map["t-filtered"] = filtered_entry

        included_entry = {"source_guid": "sg-included", "content": {"text": "ok"}}
        BatchContextMetadata.set_filter_status(included_entry, FilterStatus.INCLUDED)
        context_map["t-included"] = included_entry

        service._write_filtered_dispositions(context_map, "test_action")

        # Only the FILTERED record should get DISPOSITION_FILTERED
        filtered_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if _get_disposition_arg(c) == DISPOSITION_FILTERED
        ]
        assert len(filtered_calls) == 1, (
            f"Expected 1 FILTERED disposition, got {len(filtered_calls)}. "
            f"All calls: {backend.set_disposition.call_args_list}"
        )
        assert _get_record_id_arg(filtered_calls[0]) == "sg-filtered"

    def test_filtered_disposition_includes_reason(self):
        """FILTERED disposition must include the skip_reason matching online."""
        backend = _make_storage_backend()

        service = _build_processing_service(storage_backend=backend)

        context_map: dict[str, Any] = {}
        entry = {"source_guid": "sg-001", "content": {"text": "data"}}
        BatchContextMetadata.set_filter_status(entry, FilterStatus.FILTERED)
        BatchContextMetadata.set_skip_reason(entry, "guard_filter")
        context_map["t-001"] = entry

        service._write_filtered_dispositions(context_map, "test_action")

        filtered_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if _get_disposition_arg(c) == DISPOSITION_FILTERED
        ]
        assert len(filtered_calls) == 1
        reason = _get_kwarg(filtered_calls[0], "reason")
        assert reason == "guard_filter"


class TestExhaustedInputSnapshot:
    """U-3.2a: EXHAUSTED disposition must include input_snapshot like online."""

    def test_exhausted_includes_input_snapshot(self):
        """Batch EXHAUSTED disposition must write input_snapshot for forensics."""
        backend = _make_storage_backend()

        items = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "_state": RecordState.EXHAUSTED.value,
                "content": {"text": "original input"},
                "metadata": {"retry_exhausted": True},
                "_recovery": {},
            },
        ]

        write_record_dispositions(backend, items, "test_action")

        exhausted_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if _get_disposition_arg(c) == DISPOSITION_EXHAUSTED
        ]
        assert len(exhausted_calls) == 1
        input_snapshot = _get_kwarg(exhausted_calls[0], "input_snapshot")
        assert input_snapshot is not None, (
            "EXHAUSTED disposition must include input_snapshot for debugging"
        )
        # Snapshot should be valid JSON containing the record content
        parsed = json.loads(input_snapshot)
        assert "source_guid" in parsed or "content" in parsed


class TestFailedInputSnapshot:
    """U-3.2a: FAILED disposition must include input_snapshot and detail like online."""

    def test_failed_includes_input_snapshot(self):
        """Batch FAILED disposition must write input_snapshot for debugging."""
        backend = _make_storage_backend()

        items = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "_state": RecordState.FAILED.value,
                "content": {"text": "input data"},
                "metadata": {},
                "error": "provider returned 500 error",
            },
        ]

        write_record_dispositions(backend, items, "test_action")

        failed_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if _get_disposition_arg(c) == DISPOSITION_FAILED
        ]
        assert len(failed_calls) == 1
        input_snapshot = _get_kwarg(failed_calls[0], "input_snapshot")
        assert input_snapshot is not None, "FAILED disposition must include input_snapshot"

    def test_failed_includes_detail(self):
        """Batch FAILED disposition must write detail field like online."""
        backend = _make_storage_backend()

        items = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "_state": RecordState.FAILED.value,
                "content": {"text": "input"},
                "metadata": {},
                "error": "model timeout after 30s",
            },
        ]

        write_record_dispositions(backend, items, "test_action")

        failed_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if _get_disposition_arg(c) == DISPOSITION_FAILED
        ]
        assert len(failed_calls) == 1
        detail = _get_kwarg(failed_calls[0], "detail")
        assert detail is not None, "FAILED disposition must include detail"
        assert "model timeout" in detail


class TestPromptTraceOnlyForSuccess:
    """U-3.5a: Prompt trace responses written only for successful records."""

    def test_tombstone_records_not_traced(self):
        """Exhausted/failed/skipped records must NOT get prompt trace updates."""
        backend = _make_storage_backend()
        backend.update_prompt_trace_response = MagicMock()

        service = _build_processing_service(storage_backend=backend)

        items = [
            {
                "target_id": "t-success",
                "source_guid": "sg-001",
                "_state": RecordState.PROCESSED.value,
                "content": {"result": "LLM response"},
                "metadata": {},
            },
            {
                "target_id": "t-exhausted",
                "source_guid": "sg-002",
                "_state": RecordState.EXHAUSTED.value,
                "content": {"text": "original input"},
                "metadata": {"retry_exhausted": True},
            },
            {
                "target_id": "t-failed",
                "source_guid": "sg-003",
                "_state": RecordState.FAILED.value,
                "content": {"text": "input"},
                "metadata": {},
                "error": "provider error",
            },
        ]

        service._update_prompt_trace_responses(items, "test_action")

        # Only the SUCCESS record should have prompt trace updated.
        trace_calls = backend.update_prompt_trace_response.call_args_list
        traced_ids = {
            c.kwargs.get("record_id") or (c.args[1] if len(c.args) > 1 else None)
            for c in trace_calls
        }
        assert "t-success" in traced_ids, "SUCCESS record must get prompt trace"
        assert "t-exhausted" not in traced_ids, "EXHAUSTED record must NOT get prompt trace update"
        assert "t-failed" not in traced_ids, "FAILED record must NOT get prompt trace update"


# =============================================================================
# Helpers
# =============================================================================


def _build_processing_service(*, storage_backend: Any = None) -> Any:
    """Build a BatchProcessingService with minimal mocks for disposition tests."""
    from unittest.mock import MagicMock

    from agent_actions.llm.batch.services.processing import BatchProcessingService

    return BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        source_handler=None,
        action_indices={},
        dependency_configs={},
        storage_backend=storage_backend,
        workflow_name="test_action",
    )


def _get_disposition_arg(call_obj) -> str | None:
    """Extract the disposition argument from a mock call."""
    if call_obj.kwargs.get("disposition"):
        return call_obj.kwargs["disposition"]
    if len(call_obj.args) >= 3:
        return call_obj.args[2]
    return None


def _get_record_id_arg(call_obj) -> str | None:
    """Extract the record_id argument from a mock call."""
    if call_obj.kwargs.get("record_id"):
        return call_obj.kwargs["record_id"]
    if len(call_obj.args) >= 2:
        return call_obj.args[1]
    return None


def _get_kwarg(call_obj, key: str) -> Any:
    """Extract a keyword argument from a mock call."""
    return call_obj.kwargs.get(key)
