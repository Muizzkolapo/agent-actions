"""What a batch records as its input, and when it reads it.

Carry-forward resolves a stored row to the input behind it, and below an
expansion the only thing separating a producer that is gone from one this run
did not answer for is whether it still stands in the input. The context map
cannot answer that: the disposition gate narrows the input before the map is
built, so the map holds only what was submitted and every input the gate carried
looks identical to one that no longer exists.

So submission records the input as it stood before the gate, and finalize reads
it back. These tests pin both ends of that — the reading end is pinned from the
outside in ``test_batch_rerun_below_an_expansion.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.core.batch_models import SubmissionResult
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.storage.backend import DISPOSITION_SUCCESS
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "expand_question"
BATCH = "page.json"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    return store


class TestTheRecordedInputRoundTrips:
    def test_nothing_recorded_reads_as_nothing_recorded(self, backend):
        """Distinct from an empty recording: the reader infers rows away from this."""
        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) is None

    def test_what_was_saved_is_what_is_read(self, backend):
        BatchContextManager.save_batch_inputs(backend, ACTION, ["i2", "i1"], BATCH)

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"i1", "i2"}

    def test_an_empty_recording_is_not_a_missing_one(self, backend):
        """A run that took no input recorded that, and it must not read as unknown."""
        BatchContextManager.save_batch_inputs(backend, ACTION, [], BATCH)

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == set()

    def test_the_recording_is_scoped_to_its_own_batch(self, backend):
        """One file's input must never answer for another's."""
        BatchContextManager.save_batch_inputs(backend, ACTION, ["i1"], "page.json")
        BatchContextManager.save_batch_inputs(backend, ACTION, ["i9"], "other.json")

        assert BatchContextManager.load_batch_inputs(backend, ACTION, "page.json") == {"i1"}
        assert BatchContextManager.load_batch_inputs(backend, ACTION, "other.json") == {"i9"}

    def test_a_path_traversing_batch_name_is_refused(self, backend):
        """Refused the same way the context map refuses it, and nothing is written."""
        with pytest.raises(ProcessingError):
            BatchContextManager.save_batch_inputs(backend, ACTION, ["i1"], "../escape.json")
        assert BatchContextManager.load_batch_inputs(backend, ACTION, "escape.json") is None


def _service(backend: SQLiteBackend) -> BatchSubmissionService:
    """A submission service whose gate and store are real; the provider is not.

    Submissions below pass ``force=True``: the registry is a mock, so its entry
    reads as in-flight and the real guard would return before anything is recorded.
    """
    service = BatchSubmissionService(
        task_preparator=MagicMock(),
        client_resolver=MagicMock(),
        context_manager=BatchContextManager(),
        registry_manager_factory=MagicMock(),
        storage_backend=backend,
        disposition_gate=DispositionGate(storage_backend=backend),
    )
    service._submit_to_provider = MagicMock(  # type: ignore[method-assign]
        return_value=SubmissionResult(batch_id="batch-1")
    )
    service._stamp_deferred = MagicMock()  # type: ignore[method-assign]
    return service


def _prepared(service: BatchSubmissionService, submitted: list[dict[str, Any]]) -> None:
    """Stand in for preparation, which returns a map of only what it was handed."""
    context_map = {
        row.get("source_guid", f"t{index}"): dict(row) for index, row in enumerate(submitted)
    }
    service.prepare_batch_tasks = MagicMock(  # type: ignore[method-assign]
        return_value=([{"target_id": key} for key in context_map], context_map)
    )


class TestSubmissionRecordsTheInputBeforeTheGateNarrowsIt:
    def test_an_input_the_gate_carried_is_still_recorded(self, backend, tmp_path):
        """The whole point: what the gate removes must survive in the recording.

        Recorded after narrowing instead, an ordinary incremental run would report
        only the records it resubmitted, and carry-forward would read every
        already-done input as a generation that no longer exists.
        """
        backend.set_disposition(ACTION, "i1", DISPOSITION_SUCCESS)
        service = _service(backend)
        data = [{"source_guid": "i1", "text": "a"}, {"source_guid": "i2", "text": "b"}]
        # Only i2 survives the gate, so only i2 reaches preparation.
        _prepared(service, [data[1]])

        service.submit_batch_job(
            agent_config={"action_name": ACTION, "kind": "llm"},
            batch_name=BATCH,
            data=data,
            output_directory=str(tmp_path / "out"),
            force=True,
        )

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"i1", "i2"}, (
            "the gate-carried input was left out of the recording"
        )

    def test_a_run_the_gate_did_not_narrow_records_everything(self, backend, tmp_path):
        service = _service(backend)
        data = [{"source_guid": "i1", "text": "a"}, {"source_guid": "i2", "text": "b"}]
        _prepared(service, data)

        service.submit_batch_job(
            agent_config={"action_name": ACTION, "kind": "llm"},
            batch_name=BATCH,
            data=data,
            output_directory=str(tmp_path / "out"),
            force=True,
        )

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"i1", "i2"}

    def test_a_row_carrying_no_identity_is_left_out_rather_than_recorded_as_none(
        self, backend, tmp_path
    ):
        """A recording holding None would match a row's absent producer field."""
        service = _service(backend)
        data = [{"source_guid": "i1", "text": "a"}, {"text": "no identity"}]
        _prepared(service, data)

        service.submit_batch_job(
            agent_config={"action_name": ACTION, "kind": "llm"},
            batch_name=BATCH,
            data=data,
            output_directory=str(tmp_path / "out"),
            force=True,
        )

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"i1"}
