"""What the batch path records as this run's input, measured at the fork.

Carry-forward reads the recorded input to tell a producer that no longer exists
from one this run simply did not answer for, and it deletes the stored rows of
the first. So the set it reads has to be the action's input *above* every
narrowing. Three sit above the submission: the action's ``record_limit``, the
records a repair names, and the disposition gate. A record dropped by any of them
still holds rows this action must carry, and recording the narrowed list instead
turns a re-run of one record into a delete of every other record's rows.

``pipeline.py`` already keeps that list for the online path as
``offered_to_repair``. These tests pin that the batch branch of the same fork is
given it too — the online branch's own use of it is pinned in
``tests/unit/processing/test_repair_of_minted_rows.py``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.llm.batch.core.batch_models import SubmissionResult
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline

ACTION = "expand_question"


def _records(*guids: str) -> list[dict[str, Any]]:
    return [{"source_guid": guid, "text": f"text-{guid}"} for guid in guids]


def _run_fork(
    data: list[dict[str, Any]],
    *,
    action_config: dict[str, Any] | None = None,
    retried: frozenset[str] = frozenset(),
) -> tuple[list[str] | None, list[str] | None]:
    """Drive the narrow-then-fork path; return (submitted guids, recorded guids)."""
    config = PipelineConfig(
        action_config={
            "kind": "llm",
            "run_mode": RunMode.BATCH,
            "action_name": ACTION,
            **(action_config or {}),
        },
        action_name=ACTION,
        idx=0,
        action_configs={},
        storage_backend=None,
        workflow_metadata={},
        retried_records=retried,
    )
    pipeline = ProcessingPipeline(config)

    captured: dict[str, Any] = {}

    def _capture(*args, **kwargs):
        # Positional signature: (agent_config, batch_name, data, output_directory, ...)
        captured["data"] = args[2] if len(args) > 2 else kwargs.get("data")
        captured["run_inputs"] = kwargs.get("run_inputs")
        return SubmissionResult(batch_id=None, passthrough={"carry_forward_only": True})

    with (
        patch(
            "agent_actions.llm.batch.services.submission.BatchSubmissionService.submit_batch_job",
            side_effect=_capture,
        ),
        patch("agent_actions.workflow.pipeline.FileReader", MagicMock()),
    ):
        pipeline._process_by_strategy(data, "in/page.json", "in", "out")

    def guids(rows):
        return None if rows is None else [row["source_guid"] for row in rows]

    return guids(captured.get("data")), guids(captured.get("run_inputs"))


class TestTheRecordedInputSitsAboveEveryNarrowing:
    def test_a_record_limit_drops_a_record_from_the_batch_but_not_the_recording(self):
        """The dropped record still holds rows this action must carry."""
        submitted, recorded = _run_fork(
            _records("i1", "i2", "i3"), action_config={"record_limit": 1}
        )

        assert submitted == ["i1"], f"the limit did not narrow the batch: {submitted}"
        assert recorded == ["i1", "i2", "i3"], (
            f"the recording was taken below the limit, so i2/i3 read as gone: {recorded}"
        )

    def test_a_repair_narrows_the_batch_but_not_the_recording(self):
        """`agac retry` names one record; the rest are still inputs of this run.

        This is the case that deletes most: recorded below the repair narrowing,
        every record the repair did not name reads as a generation that is gone.
        """
        submitted, recorded = _run_fork(_records("i1", "i2", "i3"), retried=frozenset({"i2"}))

        assert submitted == ["i2"], f"the repair did not narrow the batch: {submitted}"
        assert recorded == ["i1", "i2", "i3"], (
            f"the recording was taken below the repair, so i1/i3 read as gone: {recorded}"
        )

    def test_an_unnarrowed_run_records_exactly_what_it_submits(self):
        submitted, recorded = _run_fork(_records("i1", "i2"))

        assert submitted == ["i1", "i2"]
        assert recorded == ["i1", "i2"]

    def test_the_recording_is_handed_over_at_all(self):
        """A None recording disables the inference, so forgetting to pass it is silent."""
        _submitted, recorded = _run_fork(_records("i1"))

        assert recorded is not None, (
            "run_inputs never reached submit_batch_job — carry-forward would infer nothing"
        )


@pytest.mark.parametrize("retried", [frozenset(), frozenset({"i2"})])
def test_the_recording_always_covers_what_was_submitted(retried):
    """Whatever the narrowing, the recording is never a subset of the batch."""
    submitted, recorded = _run_fork(
        _records("i1", "i2", "i3"), action_config={"record_limit": 2}, retried=retried
    )

    assert recorded is not None and submitted is not None
    assert set(submitted) <= set(recorded), (
        f"submitted records missing from the recording: {set(submitted) - set(recorded)}"
    )


class TestTheFirstStageBatchPathRecordsItTheSameWay:
    """Staging has its own copy of the narrow-then-fork shape, and its own bug to avoid."""

    @staticmethod
    def _stage(tmp_path, rows, *, agent_config=None, retried=frozenset()):
        """Drive process_initial_stage in batch mode; return the ctx it forked with."""
        from agent_actions.input.preprocessing.staging import initial_pipeline as stage
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()

        base = tmp_path / "base"
        base.mkdir()
        (tmp_path / "out").mkdir()
        (base / "sample.json").write_text(json.dumps(rows))

        captured: dict[str, Any] = {}

        def _capture(batch_ctx):
            captured["ctx"] = batch_ctx
            return "out/sample.json"

        with patch.object(stage, "_process_batch_mode", side_effect=_capture):
            stage.process_initial_stage(
                stage.InitialStageContext(
                    agent_config={
                        "run_mode": "batch",
                        "context_scope": {"observe": ["source.*"]},
                        **(agent_config or {}),
                    },
                    agent_name=ACTION,
                    file_path=str(base / "sample.json"),
                    base_directory=str(base),
                    output_directory=str(tmp_path / "out"),
                    storage_backend=backend,
                    retried_records=retried,
                )
            )
        return captured["ctx"]

    def test_an_unnarrowed_chunk_is_recorded_whole(self, tmp_path):
        """The floor: staging forks with a recording, and it holds every staged row.

        The narrowing property is pinned by the record_limit case below — both
        narrowings sit under the same capture line, so one of them proves the line's
        position.
        """
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        ctx = self._stage(tmp_path, rows)

        assert ctx.run_inputs is not None, "staging forked without recording its input"
        assert len(ctx.run_inputs) == 3, (
            f"the recording lost rows the chunk started with: {len(ctx.run_inputs)}"
        )

    def test_a_record_limit_narrows_the_chunk_but_not_the_recording(self, tmp_path):
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        ctx = self._stage(tmp_path, rows, agent_config={"record_limit": 1})

        assert len(ctx.data_chunk) == 1, f"the limit did not narrow the chunk: {ctx.data_chunk}"
        assert ctx.run_inputs is not None and len(ctx.run_inputs) == 3, (
            "the recording was taken below the limit, so the dropped rows read as gone: "
            f"{ctx.run_inputs}"
        )


class TestAFileReadIsItsOwnRecording:
    """No narrowing sits above a whole-file read, so the read is the recording.

    "The caller did not say what it narrowed from" must not be read as "the input
    was empty", and on this path there is nothing to say: the batch generator reads
    the file itself.
    """

    @staticmethod
    def _submit_from_file(tmp_path, rows, *, retried=frozenset()):
        from agent_actions.workflow.pipeline import BatchPipelineParams, ProcessingPipeline

        base = tmp_path / "base"
        base.mkdir()
        (tmp_path / "out").mkdir()
        (base / "page.json").write_text(json.dumps(rows))

        captured: dict[str, Any] = {}

        def _capture(*args, **kwargs):
            captured["run_inputs"] = kwargs.get("run_inputs")
            return SubmissionResult(batch_id=None, passthrough={"carry_forward_only": True})

        with patch(
            "agent_actions.llm.batch.services.submission.BatchSubmissionService.submit_batch_job",
            side_effect=_capture,
        ):
            ProcessingPipeline._handle_batch_generation(
                BatchPipelineParams(
                    pipeline_action_config={"kind": "llm", "action_name": ACTION},
                    pipeline_action_name=ACTION,
                    batch_file_path=str(base / "page.json"),
                    batch_base_directory=str(base),
                    batch_output_directory=str(tmp_path / "out"),
                    retried_records=retried,
                )
            )
        return captured["run_inputs"]

    def test_the_file_it_read_is_what_it_records(self, tmp_path):
        rows = [{"source_guid": "i1"}, {"source_guid": "i2"}]

        recorded = self._submit_from_file(tmp_path, rows)

        assert recorded is not None, "a whole-file read recorded nothing"
        assert [r["source_guid"] for r in recorded] == ["i1", "i2"]

    def test_a_repair_on_this_path_is_not_refused(self, tmp_path):
        """The refusal is for a caller that narrowed and did not say so."""
        rows = [{"source_guid": "i1"}, {"source_guid": "i2"}]

        recorded = self._submit_from_file(tmp_path, rows, retried=frozenset({"i2"}))

        assert [r["source_guid"] for r in recorded] == ["i1", "i2"]


class TestStagingHandsTheRecordingToTheSubmission:
    """The capture is only worth as much as the handoff below it."""

    def test_process_batch_mode_forwards_the_recording(self, tmp_path):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            BatchProcessingContext,
            _process_batch_mode,
        )

        base = tmp_path / "base"
        base.mkdir()
        (tmp_path / "out").mkdir()
        (base / "page.json").write_text(json.dumps([{"text": "x"}]))
        recorded_input = [{"source_guid": "i1"}, {"source_guid": "i2"}]

        captured: dict[str, Any] = {}
        with patch("agent_actions.llm.batch.services.submission.BatchSubmissionService") as MockSvc:
            MockSvc.return_value.submit_batch_job.side_effect = lambda *a, **k: captured.update(
                k
            ) or SubmissionResult(batch_id="b1")
            _process_batch_mode(
                BatchProcessingContext(
                    agent_config={"run_mode": "batch"},
                    agent_name=ACTION,
                    data_chunk=[{"batch_id": "b1", "batch_uuid": "b1_0", "content": "x"}],
                    file_path=str(base / "page.json"),
                    base_directory=str(base),
                    output_directory=str(tmp_path / "out"),
                    run_inputs=recorded_input,
                )
            )

        assert captured.get("run_inputs") == recorded_input, (
            "the staged recording never reached the submission, so nothing is recorded"
        )
