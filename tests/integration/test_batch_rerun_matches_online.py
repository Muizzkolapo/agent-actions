"""A batch re-run leaves in an action's output file what an online re-run does.

Both paths share everything above the fork and then diverge. Online writes rows for this
run's inputs only -- the ones it processed and the ones the gate carried -- and re-answers
an input the gate calls done whose stored row is missing. Each scenario here is run
through both real paths against a real store, and the files must end up the same.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# unified imports pipeline_file_mode, which imports workflow; stub it as the online
# processor's own tests do.
if "agent_actions.workflow.pipeline_file_mode" not in sys.modules:
    sys.modules["agent_actions.workflow.pipeline_file_mode"] = MagicMock()

from agent_actions.llm.batch.core.batch_models import (  # noqa: E402
    BatchIdentity,
    RecoveryContext,
    SubmissionResult,
)
from agent_actions.llm.batch.infrastructure.context import BatchContextManager  # noqa: E402
from agent_actions.llm.batch.services.processing import BatchProcessingService  # noqa: E402
from agent_actions.llm.batch.services.processing_recovery import (  # noqa: E402
    finalize_batch_output,
)
from agent_actions.llm.batch.services.submission import BatchSubmissionService  # noqa: E402
from agent_actions.output.writer import FileWriter  # noqa: E402
from agent_actions.processing.disposition_gate import DispositionGate  # noqa: E402
from agent_actions.processing.types import ProcessingContext, ProcessingResult  # noqa: E402
from agent_actions.processing.unified import UnifiedProcessor  # noqa: E402
from agent_actions.storage.backend import DISPOSITION_SUCCESS  # noqa: E402
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend  # noqa: E402

ACTION = "write_question"
FILE = "page.json"


def _input(guid: str) -> dict[str, Any]:
    return {"source_guid": guid, "parent_source_guid": "S", "content": {"flatten": {"item": guid}}}


def _answer(guid: str, run: int) -> dict[str, Any]:
    return {
        "source_guid": guid,
        "parent_source_guid": "S",
        "answer": f"run-{run}-answer-for-{guid}",
        "_state": "processed",
        "_delta_mode": "full",
    }


def _stored(backend: SQLiteBackend) -> dict[str, str]:
    """Identity -> answer for every row the file now holds; a duplicate identity raises."""
    backend._reconstruction_cache.clear()
    rows = backend.read_target_for_rewrite(ACTION, FILE)
    held = {row["source_guid"]: row["answer"] for row in rows}
    assert len(held) == len(rows), [row["source_guid"] for row in rows]
    return held


class _Online:
    """The online path: UnifiedProcessor, the real gate and the real store."""

    def __init__(self, tmp_path: Path) -> None:
        self.backend = SQLiteBackend(str(tmp_path / "online.db"), workflow_name="w")
        self.backend.initialize()
        self.out = tmp_path / "online" / ACTION
        self.out.mkdir(parents=True)
        self.processed: list[list[str]] = []

    def run(self, run: int, inputs: list[str]) -> dict[str, str]:
        records = [_input(guid) for guid in inputs]
        taken: list[str] = []

        class Strategy:
            def invoke(self, batch: list[dict[str, Any]], context: ProcessingContext):
                taken.extend(record["source_guid"] for record in batch)
                return [
                    ProcessingResult.success(
                        data=[_answer(record["source_guid"], run)],
                        source_guid=record["source_guid"],
                    )
                    for record in batch
                ]

        context = ProcessingContext(
            agent_config={"agent_type": ACTION, "name": ACTION},
            agent_name=ACTION,
            file_path=str(self.out / FILE),
            output_directory=str(self.out),
            storage_backend=self.backend,
        )
        processor = UnifiedProcessor(disposition_gate=DispositionGate(storage_backend=self.backend))
        with patch.object(processor, "_guard_filter", return_value=(records, [])):
            output, _ = processor.process(records, context, Strategy())
        FileWriter(
            str(self.out / FILE),
            storage_backend=self.backend,
            action_name=ACTION,
            output_directory=str(self.out),
        ).write_target(output)
        for guid in taken:
            self.backend.set_disposition(ACTION, guid, DISPOSITION_SUCCESS)
        self.processed.append(sorted(taken))
        return _stored(self.backend)


class _Batch:
    """The batch path: real submission, gate, finalize and store; the provider is not."""

    def __init__(self, tmp_path: Path) -> None:
        self.backend = SQLiteBackend(str(tmp_path / "batch.db"), workflow_name="w")
        self.backend.initialize()
        self.out = tmp_path / "batch" / ACTION
        self.out.mkdir(parents=True)
        self.processed: list[list[str]] = []

    def run(self, run: int, inputs: list[str]) -> dict[str, str]:
        records = [_input(guid) for guid in inputs]
        submitted: list[dict[str, Any]] = []

        submission = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=BatchContextManager(),
            registry_manager_factory=MagicMock(),
            storage_backend=self.backend,
            disposition_gate=DispositionGate(storage_backend=self.backend),
        )
        submission._submit_to_provider = MagicMock(  # type: ignore[method-assign]
            return_value=SubmissionResult(batch_id=f"batch-{run}")
        )
        submission._stamp_deferred = MagicMock()  # type: ignore[method-assign]

        def prepare(agent_config, data, *args, **kwargs):
            submitted.extend(data)
            context_map = {row["source_guid"]: dict(row) for row in data}
            return [{"target_id": key} for key in context_map], context_map

        submission.prepare_batch_tasks = MagicMock(side_effect=prepare)  # type: ignore[method-assign]
        submission.submit_batch_job(
            agent_config={"action_name": ACTION, "kind": "llm"},
            batch_name=FILE,
            data=records,
            output_directory=str(self.out),
            force=True,
            run_inputs=records,
        )
        taken = sorted(row["source_guid"] for row in submitted)
        self.processed.append(taken)
        if not taken:
            # Nothing was sent, so nothing finalizes and the file is left as it stands.
            return _stored(self.backend)

        processing = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            workflow_name=ACTION,
            storage_backend=self.backend,
        )
        processing._convert_batch_results_to_workflow_format = MagicMock(  # type: ignore[method-assign]
            return_value=([_answer(guid, run) for guid in taken], MagicMock(), None)
        )
        context = RecoveryContext(
            service=processing,
            manager=MagicMock(),
            provider=MagicMock(),
            agent_config={"kind": "llm"},
            output_directory=str(self.out),
            action_name=ACTION,
            start_time=0.0,
        )
        identity = BatchIdentity(batch_id=f"batch-{run}", file_name=FILE, entry=MagicMock())
        context_map = {row["source_guid"]: dict(row) for row in submitted}
        finalize_batch_output(context, identity, batch_results=[], context_map=context_map)
        for guid in taken:
            self.backend.set_disposition(ACTION, guid, DISPOSITION_SUCCESS)
        return _stored(self.backend)


SCENARIOS = {
    "upstream_mints_its_children_again_each_run": [["a1", "a2"], ["a3", "a4"], ["a5", "a6"]],
    "a_new_input_joins_ones_already_done": [["a1", "a2"], ["a1", "a2", "a3"]],
    "an_input_leaves_while_another_is_new": [["a1", "a2"], ["a1", "a3"]],
    "an_input_leaves_then_returns_beside_a_new_one": [
        ["a1", "a2"],
        ["a1", "a3"],
        ["a1", "a2", "a4"],
    ],
    "a_completely_new_batch_of_records": [["r1", "r2"], ["r3"]],
    "half_the_children_are_minted_again": [["a1", "a2", "b1"], ["a3", "a4", "b1"]],
}


@pytest.mark.parametrize("runs", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_batch_leaves_what_online_leaves(tmp_path, runs):
    online, batch = _Online(tmp_path), _Batch(tmp_path)

    for number, inputs in enumerate(runs, start=1):
        expected = online.run(number, inputs)
        actual = batch.run(number, inputs)
        assert sorted(actual) == sorted(expected), (
            f"run {number} over {inputs}: online holds {sorted(expected)}, "
            f"batch holds {sorted(actual)}"
        )
        assert actual == expected, f"run {number}: the answers differ"

    assert batch.processed == online.processed, "the two paths answered different inputs"


def test_a_one_to_one_action_below_an_expansion_stays_at_its_input_size(tmp_path):
    """#1155, stated on its own: 2, 2, 2 where it was 2, 4, 6."""
    batch = _Batch(tmp_path)

    sizes = [len(batch.run(n, [f"a{2 * n - 1}", f"a{2 * n}"])) for n in range(1, 4)]

    assert sizes == [2, 2, 2]


def test_an_input_called_done_whose_row_is_gone_is_answered_again(tmp_path):
    """Online re-queues it; left out, batch would never answer it again."""
    batch = _Batch(tmp_path)
    batch.run(1, ["a1", "a2"])
    batch.run(2, ["a1", "a3"])

    held = batch.run(3, ["a1", "a2", "a4"])

    assert batch.processed[2] == ["a2", "a4"]
    assert held["a2"] == "run-3-answer-for-a2"
    assert held["a1"] == "run-1-answer-for-a1", "an input still done and stored is not re-answered"
