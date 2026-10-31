"""Batch retrieve writes dispositions and prompt traces by the online collector's rules.

FILTERED records get the disposition and reason online writes. The SUCCESS,
FAILED and EXHAUSTED parity, with input snapshots and details, is pinned on the
path finalize runs in tests/unit/llm/batch/test_batch_collect_writes_dispositions.py.

Prompt trace responses are written only for SUCCESS records, not for tombstones
or passthroughs.
"""

from typing import Any
from unittest.mock import MagicMock

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.services.collect import (
    update_prompt_trace_responses,
    write_filtered_dispositions,
)
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import (
    DISPOSITION_FILTERED,
)


def _make_storage_backend() -> MagicMock:
    """Create a mock storage backend that tracks disposition calls."""
    backend = MagicMock()
    backend.set_disposition = MagicMock()
    backend.clear_disposition = MagicMock()
    return backend


class TestFilteredDisposition:
    """FILTERED records must get DISPOSITION_FILTERED like online."""

    def test_filtered_record_gets_filtered_disposition(self):
        """Records filtered during batch prep must receive DISPOSITION_FILTERED.

        The online path writes DISPOSITION_FILTERED for ProcessingStatus.FILTERED.
        The batch path must do the same for records with FilterStatus.FILTERED
        in the context_map.
        """
        backend = _make_storage_backend()

        # FILTERED records are excluded from workflow output items, so they
        # are dispositioned from the context map.
        context_map: dict[str, Any] = {}
        filtered_entry = {"source_guid": "sg-filtered", "content": {"text": "data"}}
        BatchContextMetadata.set_filter_status(filtered_entry, FilterStatus.FILTERED)
        BatchContextMetadata.set_skip_reason(filtered_entry, "guard_filter")
        context_map["t-filtered"] = filtered_entry

        included_entry = {"source_guid": "sg-included", "content": {"text": "ok"}}
        BatchContextMetadata.set_filter_status(included_entry, FilterStatus.INCLUDED)
        context_map["t-included"] = included_entry

        write_filtered_dispositions(backend, "test_action", context_map)

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

        context_map: dict[str, Any] = {}
        entry = {"source_guid": "sg-001", "content": {"text": "data"}}
        BatchContextMetadata.set_filter_status(entry, FilterStatus.FILTERED)
        BatchContextMetadata.set_skip_reason(entry, "guard_filter")
        context_map["t-001"] = entry

        write_filtered_dispositions(backend, "test_action", context_map)

        filtered_calls = [
            c
            for c in backend.set_disposition.call_args_list
            if _get_disposition_arg(c) == DISPOSITION_FILTERED
        ]
        assert len(filtered_calls) == 1
        reason = _get_kwarg(filtered_calls[0], "reason")
        assert reason == "guard_filter"


class TestPromptTraceOnlyForSuccess:
    """Prompt trace responses written only for successful records."""

    def test_tombstone_records_not_traced(self):
        """Exhausted/failed/skipped records must NOT get prompt trace updates."""
        backend = _make_storage_backend()
        backend.update_prompt_trace_response = MagicMock()

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

        update_prompt_trace_responses(backend, "test_action", items)

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
