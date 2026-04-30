"""Tests for initial pipeline return contract (P1 #1).

Both _process_batch_mode() and _process_online_mode_with_record_processor()
must return a string path to the output file.

Also covers failure-path behaviour (#82): zero-output detection, guard-skip
disposition, and tool-action empty-output check.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.input.preprocessing.staging.initial_pipeline import (
    BatchProcessingContext,
    InitialStageContext,
    _process_batch_mode,
    _process_online_mode_with_record_processor,
)
from agent_actions.llm.batch.core.batch_models import SubmissionResult
from agent_actions.processing.result_collector import CollectionStats
from agent_actions.record.state import RecordState


@pytest.fixture
def tmp_dirs(tmp_path):
    """Create base and output directories with a sample input file."""
    base = tmp_path / "base"
    output = tmp_path / "output"
    base.mkdir()
    output.mkdir()
    input_file = base / "sample.json"
    input_file.write_text(json.dumps([{"text": "hello"}]))
    return base, output, input_file


class TestBatchModeReturnsPath:
    def test_returns_string_path_on_normal_result(self, tmp_dirs):
        base, output, input_file = tmp_dirs
        ctx = BatchProcessingContext(
            agent_config={"run_mode": "batch"},
            agent_name="test_agent",
            data_chunk=[{"batch_id": "b1", "batch_uuid": "b1_0", "content": "x"}],
            file_path=str(input_file),
            base_directory=str(base),
            output_directory=str(output),
        )

        with patch(
            "agent_actions.llm.batch.services.submission.BatchSubmissionService"
        ) as MockSubmission:
            MockSubmission.return_value.submit_batch_job.return_value = SubmissionResult(
                batch_id="vendor_id_123"
            )
            result = _process_batch_mode(ctx)

        assert isinstance(result, str)
        assert result.endswith(".json")

    def test_returns_string_path_on_tombstone_result(self, tmp_dirs):
        base, output, input_file = tmp_dirs
        storage = MagicMock()
        ctx = BatchProcessingContext(
            agent_config={"run_mode": "batch"},
            agent_name="test_agent",
            data_chunk=[{"batch_id": "b1", "batch_uuid": "b1_0", "content": "x"}],
            file_path=str(input_file),
            base_directory=str(base),
            output_directory=str(output),
            storage_backend=storage,
        )

        tombstone = {"type": "tombstone", "data": [{"status": "skipped"}]}
        with (
            patch(
                "agent_actions.llm.batch.services.submission.BatchSubmissionService"
            ) as MockSubmission,
            patch("agent_actions.input.preprocessing.staging.initial_pipeline.FileWriter"),
        ):
            MockSubmission.return_value.submit_batch_job.return_value = SubmissionResult(
                passthrough=tombstone
            )
            result = _process_batch_mode(ctx)

        assert isinstance(result, str)
        assert result.endswith(".json")


class TestOnlineModeReturnsPath:
    def test_returns_string_path(self, tmp_dirs):
        base, output, input_file = tmp_dirs
        storage = MagicMock()
        ctx = InitialStageContext(
            agent_config={},
            agent_name="test_agent",
            file_path=str(input_file),
            base_directory=str(base),
            output_directory=str(output),
            storage_backend=storage,
        )
        data_chunk = [{"content": "hello"}]

        with (
            patch(
                "agent_actions.input.preprocessing.staging.initial_pipeline.UnifiedProcessor"
            ) as MockProc,
            patch("agent_actions.input.preprocessing.staging.initial_pipeline.FileWriter"),
        ):
            MockProc.return_value.process.return_value = (
                [{"result": "ok"}],
                CollectionStats(success=1),
            )

            result = _process_online_mode_with_record_processor(
                data_chunk, ctx, str(input_file), str(base), str(output)
            )

        assert isinstance(result, str)
        assert result.endswith(".json")


class TestInitialPipelineZeroSuccessFailure:
    """Tests for the zero-success failure check in initial pipeline.

    When all records fail or exhaust retries (stats.success == 0 and
    stats.failed + stats.exhausted > 0), the initial pipeline should raise
    RuntimeError so the executor marks the action as failed and the circuit
    breaker skips downstream dependents.
    """

    def _run_online(self, tmp_dirs, stats, output=None):
        """Call _process_online_mode_with_record_processor with mocked stats."""
        base, output_dir, input_file = tmp_dirs
        storage = MagicMock()
        ctx = InitialStageContext(
            agent_config={},
            agent_name="test_agent",
            file_path=str(input_file),
            base_directory=str(base),
            output_directory=str(output_dir),
            storage_backend=storage,
        )
        data_chunk = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
        if output is None:
            output = data_chunk

        with (
            patch(
                "agent_actions.input.preprocessing.staging.initial_pipeline.UnifiedProcessor"
            ) as MockProc,
            patch("agent_actions.input.preprocessing.staging.initial_pipeline.FileWriter"),
        ):
            MockProc.return_value.process.return_value = (output, stats)

            return _process_online_mode_with_record_processor(
                data_chunk, ctx, str(input_file), str(base), str(output_dir)
            )

    def test_all_failed_raises(self, tmp_dirs):
        """All records FAILED -> RuntimeError."""
        stats = CollectionStats(failed=3)
        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            self._run_online(tmp_dirs, stats, output=[])

    def test_all_exhausted_raises(self, tmp_dirs):
        """All records EXHAUSTED (tombstones in output) -> RuntimeError."""
        stats = CollectionStats(exhausted=3)
        tombstones = [{"_state": RecordState.EXHAUSTED.value}] * 3
        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            self._run_online(tmp_dirs, stats, output=tombstones)

    def test_mixed_failed_exhausted_raises(self, tmp_dirs):
        """Mixed FAILED + EXHAUSTED -> RuntimeError with both counts."""
        stats = CollectionStats(failed=2, exhausted=1)
        with pytest.raises(RuntimeError, match=r"2 failed, 1 exhausted"):
            self._run_online(tmp_dirs, stats, output=[{"_state": RecordState.EXHAUSTED.value}])

    def test_partial_success_no_raise(self, tmp_dirs):
        """Some succeed + some fail -> no raise."""
        stats = CollectionStats(success=1, failed=2)
        result = self._run_online(tmp_dirs, stats, output=[{"result": "ok"}])
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Guard-skip, empty-input, and tool-action tests (#82)
# ---------------------------------------------------------------------------

_PATCH_PREFIX = "agent_actions.input.preprocessing.staging.initial_pipeline"


@pytest.fixture
def online_ctx(tmp_dirs):
    """Reusable online-mode context with mocked storage backend."""
    base, output, input_file = tmp_dirs
    storage = MagicMock()
    ctx = InitialStageContext(
        agent_config={},
        agent_name="test_agent",
        file_path=str(input_file),
        base_directory=str(base),
        output_directory=str(output),
        storage_backend=storage,
    )
    return ctx, base, output, input_file


def _call_online(data_chunk, ctx, input_file, base, output):
    """Helper to invoke _process_online_mode_with_record_processor."""
    return _process_online_mode_with_record_processor(
        data_chunk, ctx, str(input_file), str(base), str(output)
    )


class TestInitialPipelineGuardSkipAndToolAction:
    """Tests for guard-skip disposition, empty input, and tool-action check."""

    def test_guard_skip_writes_disposition_and_does_not_raise(self, online_ctx):
        """All records guard-skipped -> disposition written, no raise."""
        ctx, base, output, input_file = online_ctx
        data_chunk = [{"id": "1"}]

        with (
            patch(f"{_PATCH_PREFIX}.UnifiedProcessor") as MockProc,
            patch(f"{_PATCH_PREFIX}.FileWriter"),
        ):
            MockProc.return_value.process.return_value = ([], CollectionStats())

            result = _call_online(data_chunk, ctx, input_file, base, output)

        assert isinstance(result, str)
        ctx.storage_backend.set_disposition.assert_called_once_with(
            "test_agent",
            "__node__",
            "skipped",
            reason="All records filtered — no output produced",
        )

    def test_unprocessed_empty_data_does_not_write_skip_disposition(self, online_ctx):
        """Bug #10: UNPROCESSED with empty data → empty output, must NOT trigger SKIPPED.

        Records were unprocessed (not filtered). The disposition condition must
        check stats.unprocessed to avoid falsely writing SKIPPED.
        """
        ctx, base, output, input_file = online_ctx
        data_chunk = [{"id": "1"}, {"id": "2"}]

        with (
            patch(f"{_PATCH_PREFIX}.UnifiedProcessor") as MockProc,
            patch(f"{_PATCH_PREFIX}.FileWriter"),
        ):
            MockProc.return_value.process.return_value = ([], CollectionStats(unprocessed=2))

            result = _call_online(data_chunk, ctx, input_file, base, output)

        assert isinstance(result, str)
        ctx.storage_backend.set_disposition.assert_not_called()

    def test_empty_input_does_not_raise(self, online_ctx):
        """Empty input -> no failure check fires."""
        ctx, base, output, input_file = online_ctx
        data_chunk = []

        with (
            patch(f"{_PATCH_PREFIX}.UnifiedProcessor") as MockProc,
            patch(f"{_PATCH_PREFIX}.FileWriter"),
        ):
            MockProc.return_value.process.return_value = ([], CollectionStats())

            result = _call_online(data_chunk, ctx, input_file, base, output)
            assert isinstance(result, str)

    @pytest.mark.parametrize(
        "config",
        [
            {"model_vendor": "tool"},
            {"kind": "tool"},
        ],
        ids=["model_vendor=tool", "kind=tool"],
    )
    def test_tool_action_empty_output_raises(self, online_ctx, config):
        """Tool action with success but empty output must raise."""
        ctx, base, output, input_file = online_ctx
        ctx.agent_config = config
        data_chunk = [{"id": "1"}]

        with (
            patch(f"{_PATCH_PREFIX}.UnifiedProcessor") as MockProc,
            patch(f"{_PATCH_PREFIX}.FileWriter"),
        ):
            MockProc.return_value.process.return_value = ([], CollectionStats(success=1))

            with pytest.raises(RuntimeError, match="tool returned empty result"):
                _call_online(data_chunk, ctx, input_file, base, output)

    def test_non_tool_action_empty_success_no_raise(self, online_ctx):
        """Non-tool action with success but empty output should NOT raise."""
        ctx, base, output, input_file = online_ctx
        ctx.agent_config = {"model_vendor": "openai"}
        data_chunk = [{"id": "1"}]

        with (
            patch(f"{_PATCH_PREFIX}.UnifiedProcessor") as MockProc,
            patch(f"{_PATCH_PREFIX}.FileWriter"),
        ):
            MockProc.return_value.process.return_value = ([], CollectionStats(success=1))

            result = _call_online(data_chunk, ctx, input_file, base, output)
            assert isinstance(result, str)
