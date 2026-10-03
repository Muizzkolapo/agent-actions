"""Batch carry-forward across re-runs, with every link real but the provider.

The runner reads the upstream output from a real store and records the pool, submission
records the run's inputs, and finalize reads both back and writes through the store. Each
link is pinned on its own elsewhere with hand-written recordings; this is the only place
the recordings one link writes are the ones the next link reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.config.types import RunMode
from agent_actions.llm.batch.core.batch_models import (
    BatchIdentity,
    RecoveryContext,
    SubmissionResult,
)
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.processing_recovery import finalize_batch_output
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.storage.backend import DISPOSITION_FILTERED
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.runner_file_processing import process_from_storage_backend

UPSTREAM = "flatten"
ACTION = "write_question"
FILE = "page.json"
STAGED = "S"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    return store


def _child(guid: str) -> dict[str, Any]:
    """A row of the upstream expansion: minted, descending from the staged record."""
    return {
        "source_guid": guid,
        "parent_source_guid": STAGED,
        "content": {UPSTREAM: {"item": guid}},
        "_state": "processed",
        "_delta_mode": "full",
    }


def _answer(guid: str) -> dict[str, Any]:
    """This action's one row for one input: it keeps the input's identity."""
    return {
        "source_guid": guid,
        "parent_source_guid": STAGED,
        "answer": f"answer-for-{guid}",
        "_state": "processed",
        "_delta_mode": "full",
    }


def _run(backend: SQLiteBackend, tmp_path: Path, run: int, upstream: list[str]) -> list[str]:
    """One full batch run of ACTION over what UPSTREAM now holds; returns the stored rows."""
    backend._write_target_raw(UPSTREAM, FILE, [_child(guid) for guid in upstream])
    backend._reconstruction_cache.clear()
    upstream_dir = tmp_path / UPSTREAM
    output_dir = tmp_path / ACTION
    upstream_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    # The runner: reads the upstream output, records the pool, drops what a guard filtered.
    runner = MagicMock()
    runner.storage_backend = backend
    params = MagicMock()
    params.upstream_data_dirs = [str(upstream_dir)]
    params.output_directory = str(output_dir)
    params.action_config = {"run_mode": RunMode.BATCH}
    params.action_name = ACTION
    params.idx = 0
    process_from_storage_backend(runner, params)
    data = runner._process_single_file.call_args[0][0].data

    # Submission: records this run's inputs beside their staged records.
    submission = BatchSubmissionService(
        task_preparator=MagicMock(),
        client_resolver=MagicMock(),
        context_manager=BatchContextManager(),
        registry_manager_factory=MagicMock(),
        storage_backend=backend,
        disposition_gate=DispositionGate(storage_backend=backend),
    )
    submission._submit_to_provider = MagicMock(  # type: ignore[method-assign]
        return_value=SubmissionResult(batch_id=f"batch-{run}")
    )
    submission._stamp_deferred = MagicMock()  # type: ignore[method-assign]
    context_map = {row["source_guid"]: dict(row) for row in data}
    submission.prepare_batch_tasks = MagicMock(  # type: ignore[method-assign]
        return_value=([{"target_id": key} for key in context_map], context_map)
    )
    submission.submit_batch_job(
        agent_config={"action_name": ACTION, "kind": "llm"},
        batch_name=FILE,
        data=data,
        output_directory=str(output_dir),
        force=True,
        run_inputs=data,
    )

    # Finalize: the provider answered every submitted input with one row.
    processing = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        workflow_name=ACTION,
        storage_backend=backend,
    )
    processing._convert_batch_results_to_workflow_format = MagicMock(  # type: ignore[method-assign]
        return_value=([_answer(row["source_guid"]) for row in data], MagicMock(), None)
    )
    context = RecoveryContext(
        service=processing,
        manager=MagicMock(),
        provider=MagicMock(),
        agent_config={"kind": "llm"},
        output_directory=str(output_dir),
        action_name=ACTION,
        start_time=0.0,
    )
    identity = BatchIdentity(batch_id=f"batch-{run}", file_name=FILE, entry=MagicMock())
    finalize_batch_output(context, identity, batch_results=[], context_map=context_map)

    backend._reconstruction_cache.clear()
    return sorted(row["source_guid"] for row in backend.read_target_for_rewrite(ACTION, FILE))


def test_a_one_to_one_action_below_an_expansion_does_not_accumulate(backend, tmp_path):
    """#1155: the upstream action mints its children under new identities every run."""
    assert _run(backend, tmp_path, 1, ["a1", "a2"]) == ["a1", "a2"]
    assert _run(backend, tmp_path, 2, ["a3", "a4"]) == ["a3", "a4"]
    assert _run(backend, tmp_path, 3, ["a5", "a6"]) == ["a5", "a6"]


def test_an_input_a_guard_filters_keeps_its_answer_across_the_run(backend, tmp_path):
    """The filtered child leaves the upstream output and keeps only a disposition, so
    without the recorded pool it is indistinguishable from one minted again."""
    assert _run(backend, tmp_path, 1, ["a1", "a2"]) == ["a1", "a2"]

    backend.set_disposition(UPSTREAM, "a2", DISPOSITION_FILTERED)

    assert _run(backend, tmp_path, 2, ["a1"]) == ["a1", "a2"]


def test_a_mint_after_a_filtered_run_replaces_the_whole_previous_generation(backend, tmp_path):
    assert _run(backend, tmp_path, 1, ["a1", "a2"]) == ["a1", "a2"]
    backend.set_disposition(UPSTREAM, "a2", DISPOSITION_FILTERED)
    assert _run(backend, tmp_path, 2, ["a1"]) == ["a1", "a2"]

    backend.clear_disposition(UPSTREAM, record_id="a2")

    assert _run(backend, tmp_path, 3, ["a7", "a8"]) == ["a7", "a8"]


def test_a_filtered_mark_left_on_a_replaced_child_keeps_its_one_row(backend, tmp_path):
    """The accepted limit: a FILTERED disposition says the record still exists, so while
    one for a child that was since minted again is left in the store, that child's row
    is kept. It is one row and does not grow."""
    assert _run(backend, tmp_path, 1, ["a1", "a2"]) == ["a1", "a2"]
    backend.set_disposition(UPSTREAM, "a2", DISPOSITION_FILTERED)

    assert _run(backend, tmp_path, 2, ["a7", "a8"]) == ["a2", "a7", "a8"]
    assert _run(backend, tmp_path, 3, ["a9", "b0"]) == ["a2", "a9", "b0"]
