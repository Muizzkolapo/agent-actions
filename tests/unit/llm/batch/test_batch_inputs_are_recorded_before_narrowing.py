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

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError, ProcessingError
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

    def test_a_recording_with_ancestors_reads_back_both_ways(self, backend):
        BatchContextManager.save_batch_inputs(backend, ACTION, {"a2": "S", "a1": "S"}, BATCH)

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"a1", "a2"}
        assert BatchContextManager.load_batch_input_ancestors(backend, ACTION, BATCH) == {
            "a1": "S",
            "a2": "S",
        }

    def test_a_recording_of_identities_alone_has_no_ancestors(self, backend):
        """What every run recorded before ancestors were: read as none, never guessed."""
        BatchContextManager.save_batch_inputs(backend, ACTION, ["i1"], BATCH)

        assert BatchContextManager.load_batch_input_ancestors(backend, ACTION, BATCH) is None

    def test_no_recording_has_no_ancestors(self, backend):
        assert BatchContextManager.load_batch_input_ancestors(backend, ACTION, BATCH) is None

    def test_the_upstream_pool_round_trips_beside_the_inputs(self, backend):
        BatchContextManager.save_batch_inputs(backend, ACTION, {"a1": "S"}, BATCH)
        BatchContextManager.save_upstream_pool(backend, ACTION, {"a2": "S", "a1": "S"}, BATCH)

        assert BatchContextManager.load_upstream_pool(backend, ACTION, BATCH) == {
            "a1": "S",
            "a2": "S",
        }
        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"a1"}

    def test_no_recorded_pool_reads_as_none(self, backend):
        assert BatchContextManager.load_upstream_pool(backend, ACTION, BATCH) is None

    def test_an_unreadable_pool_reads_as_none(self, backend):
        backend.save_metadata(f"batch_inputs:{ACTION}:pool:{BATCH}", "{not json")

        assert BatchContextManager.load_upstream_pool(backend, ACTION, BATCH) is None

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

    def test_an_unreadable_recording_reads_as_unrecorded(self, backend, caplog):
        """Raising would abandon a batch the provider has already answered for."""
        backend.save_metadata(f"batch_inputs:{ACTION}:{BATCH}", "{not json")

        with caplog.at_level(logging.WARNING):
            assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) is None
        assert "carrying every stored row" in caplog.text

    @pytest.mark.parametrize("blob", ['"a1"', '{"i1": 1}', "5", "null"])
    def test_a_recording_that_is_not_a_list_of_identities_reads_as_unrecorded(
        self, backend, blob, caplog
    ):
        """`set("a1")` is {"a", "1"} — a wrong input set drives a rule that deletes."""
        backend.save_metadata(f"batch_inputs:{ACTION}:{BATCH}", blob)

        with caplog.at_level(logging.WARNING):
            assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) is None

    def test_clearing_batch_state_removes_the_recording(self, backend):
        """`--fresh` and `agac retry` promise to wipe the action's batch state.

        Left behind, the recording answers for a run that no longer has one.
        """
        BatchContextManager.save_batch_inputs(backend, ACTION, ["i1"], BATCH)
        BatchContextManager.save_upstream_pool(backend, ACTION, {"i1": "i1"}, BATCH)
        BatchContextManager.save_batch_context_map(backend, ACTION, {"t0": {}}, BATCH)

        backend.clear_batch_state(ACTION)

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) is None
        assert BatchContextManager.load_upstream_pool(backend, ACTION, BATCH) is None

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
            run_inputs=data,
        )

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"i1", "i2"}, (
            "the gate-carried input was left out of the recording"
        )

    def test_each_input_is_recorded_with_the_staged_record_it_came_from(self, backend, tmp_path):
        """A child of an expansion carries its staged record; a staged row is its own."""
        service = _service(backend)
        data = [
            {"source_guid": "a1", "parent_source_guid": "S", "text": "a"},
            {"source_guid": "r2", "text": "b"},
        ]
        _prepared(service, data)

        service.submit_batch_job(
            agent_config={"action_name": ACTION, "kind": "llm"},
            batch_name=BATCH,
            data=data,
            output_directory=str(tmp_path / "out"),
            force=True,
            run_inputs=data,
        )

        assert BatchContextManager.load_batch_input_ancestors(backend, ACTION, BATCH) == {
            "a1": "S",
            "r2": "r2",
        }

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
            run_inputs=data,
        )

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"i1", "i2"}

    def test_a_repair_given_no_recording_is_refused_rather_than_narrowed(self, backend, tmp_path):
        """The same refusal the online path makes when it is handed no wider input.

        Proceeding would record the repair's own narrowing as the whole input, and
        every record it did not name would read as a generation that is gone.
        """
        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=BatchContextManager(),
            registry_manager_factory=MagicMock(),
            storage_backend=backend,
            disposition_gate=DispositionGate(storage_backend=backend, repairing={"i2"}),
        )
        data = [{"source_guid": "i1", "text": "a"}, {"source_guid": "i2", "text": "b"}]

        with pytest.raises(ConfigurationError, match="pre-narrowing input"):
            service.submit_batch_job(
                agent_config={"action_name": ACTION, "kind": "llm"},
                batch_name=BATCH,
                data=data,
                output_directory=str(tmp_path / "out"),
                force=True,
            )

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
            run_inputs=data,
        )

        assert BatchContextManager.load_batch_inputs(backend, ACTION, BATCH) == {"i1"}


class TestTheRecordingIsReadUnderTheActionThatWroteIt:
    """The key names the action, not the workflow, and the two differ per run.

    A workflow holds many actions and one store. Reading under the workflow's name
    finds nothing on every multi-action workflow, which disables the rule silently —
    the fallback for "nothing recorded" is to carry.
    """

    def test_finalize_reads_the_recording_keyed_on_the_action(self, backend, tmp_path):
        import json as _json

        from agent_actions.llm.batch.core.batch_models import BatchIdentity, RecoveryContext
        from agent_actions.llm.batch.services.processing import BatchProcessingService
        from agent_actions.llm.batch.services.processing_recovery import finalize_batch_output

        relative = "page.json"
        row = lambda guid, producer: {  # noqa: E731
            "source_guid": guid,
            "producer_source_guids": [producer],
            "answer": guid,
            "_delta_mode": "full",
            "_state": "processed",
        }
        backend._write_target_raw(ACTION, relative, [row("b1", "a1"), row("b2", "a2")])
        backend._reconstruction_cache.clear()
        backend.save_metadata(f"batch_inputs:{ACTION}:{relative}", _json.dumps(["a3", "a4"]))

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            # Deliberately NOT the action name: this is the workflow's.
            workflow_name="quiz_maker_workflow",
            storage_backend=backend,
        )
        produced = [row("b5", "a3"), row("b6", "a4")]
        service._convert_batch_results_to_workflow_format = MagicMock(  # type: ignore[method-assign]
            return_value=(produced, MagicMock(), None)
        )
        out = tmp_path / "out"
        out.mkdir()
        finalize_batch_output(
            RecoveryContext(
                service=service,
                manager=MagicMock(),
                provider=MagicMock(),
                agent_config={"kind": "llm"},
                output_directory=str(out),
                action_name=ACTION,
                start_time=0.0,
            ),
            BatchIdentity(batch_id="b1", file_name=relative, entry=MagicMock()),
            batch_results=[],
            context_map={},
        )

        backend._reconstruction_cache.clear()
        written = [r["source_guid"] for r in backend.read_target_for_rewrite(ACTION, relative)]
        assert written == ["b5", "b6"], (
            f"the recording was not found under the action's own name: {written}"
        )
