"""Tests for pipeline guard-all-skipped disposition signal.

When all records are guard-skipped/filtered (no successes, no failures,
no exhausted retries), the pipeline writes DISPOSITION_SKIPPED at node
level so the executor can mark the action as skipped in the tally.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.result_collector import CollectionStats
from agent_actions.storage.backend import DISPOSITION_SKIPPED, NODE_LEVEL_RECORD_ID


@pytest.fixture
def pipeline_and_mocks(tmp_path):
    """Create a ProcessingPipeline with mocked internals for guard-skip tests."""
    from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline

    # Create valid file paths so process() doesn't choke on relative_to
    input_file = tmp_path / "input.json"
    input_file.write_text('[{"id": "1"}]')
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    config = MagicMock(spec=PipelineConfig)
    config.action_config = {"kind": "llm"}
    config.action_name = "test_action"
    config.storage_backend = MagicMock()
    config.idx = 0
    config.action_configs = {}
    config.source_relative_path = None

    pipeline = ProcessingPipeline.__new__(ProcessingPipeline)
    pipeline.config = config
    pipeline.record_processor = MagicMock()
    pipeline.output_handler = MagicMock()
    pipeline.granularity = "record"
    pipeline.is_tool_action = False
    pipeline.is_hitl_action = False

    return pipeline, config, str(input_file), str(tmp_path), str(output_dir)


class TestGuardSkipDisposition:
    """Tests for DISPOSITION_SKIPPED write after collect_results."""

    def _run_with_stats(self, pipeline, config, stats, file_path, base_dir, output_dir, data=None):
        """Call process() with mocked collect_results stats."""
        if data is None:
            data = [{"id": "1"}, {"id": "2"}]

        pipeline.record_processor.process_batch.return_value = []

        with patch(
            "agent_actions.workflow.pipeline.ResultCollector.collect_results",
            return_value=(data, stats),
        ):
            pipeline.process(file_path, base_dir, output_dir, data=data)

    def test_writes_disposition_when_all_guard_skipped(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED should be written when all records are skipped."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(skipped=2)

        self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_called_once_with(
            "test_action",
            NODE_LEVEL_RECORD_ID,
            DISPOSITION_SKIPPED,
            reason="All records guard-skipped or filtered",
        )

    def test_writes_disposition_when_all_filtered(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED should be written when all records are filtered."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(filtered=2)

        self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_called_once()

    def test_writes_disposition_when_all_unprocessed(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED should be written when all records are unprocessed."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(unprocessed=2)

        self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_called_once()

    def test_no_disposition_when_some_succeed(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED must NOT be written if any record succeeded."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(success=1, skipped=1)

        self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_not_called()

    def test_no_disposition_when_some_failed(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED must NOT be written if any record failed (raises instead)."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(failed=1, skipped=1)

        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_not_called()

    def test_no_disposition_when_records_exhausted(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED must NOT be written if records exhausted retries (raises instead)."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(exhausted=2)

        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_not_called()

    def test_no_disposition_when_records_deferred(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED must NOT be written if records are deferred."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(deferred=2)

        self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_not_called()

    def test_no_disposition_when_data_empty(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED must NOT be written if input data is empty."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats()

        self._run_with_stats(pipeline, config, stats, fp, base, out, data=[])

        config.storage_backend.set_disposition.assert_not_called()

    def test_no_disposition_when_storage_backend_none(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED must NOT crash if storage_backend is None."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        config.storage_backend = None
        stats = CollectionStats(skipped=2)

        # Should not raise
        self._run_with_stats(pipeline, config, stats, fp, base, out)

    def test_storage_error_is_logged_not_raised(self, pipeline_and_mocks):
        """Storage errors during disposition write should be logged, not propagated."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        config.storage_backend.set_disposition.side_effect = RuntimeError("DB error")
        stats = CollectionStats(skipped=2)

        # Should not raise
        self._run_with_stats(pipeline, config, stats, fp, base, out)


class TestToolActionZeroOutputDetection:
    """Tests for the tool-specific zero-output safety net in the pipeline.

    When a tool action's result collection reports stats.success > 0 but
    output is empty, the pipeline should raise so the executor marks the
    action as failed in the tally.
    """

    def _run_with_stats(self, pipeline, config, stats, file_path, base_dir, output_dir, data=None):
        """Call process() with mocked collect_results returning empty output."""
        if data is None:
            data = [{"id": "1"}, {"id": "2"}]

        pipeline.record_processor.process_batch.return_value = []

        with patch(
            "agent_actions.workflow.pipeline.ResultCollector.collect_results",
            return_value=([], stats),  # empty output
        ):
            pipeline.process(file_path, base_dir, output_dir, data=data)

    def test_tool_action_empty_output_raises(self, pipeline_and_mocks):
        """Tool action with input but zero output (stats.success > 0) should raise."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        pipeline.is_tool_action = True
        stats = CollectionStats(success=1)

        with pytest.raises(RuntimeError, match="produced 0 output records"):
            self._run_with_stats(pipeline, config, stats, fp, base, out)

    def test_non_tool_action_empty_output_does_not_raise(self, pipeline_and_mocks):
        """Non-tool action with empty output and stats.success > 0 should NOT raise."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        pipeline.is_tool_action = False
        stats = CollectionStats(success=1)

        # Should not raise — existing behavior for non-tool actions preserved
        self._run_with_stats(pipeline, config, stats, fp, base, out)

    def test_tool_action_empty_input_does_not_raise(self, pipeline_and_mocks):
        """Tool action with empty input should NOT raise (no input = no failure)."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        pipeline.is_tool_action = True
        stats = CollectionStats()

        # Should not raise — empty input is not a failure
        self._run_with_stats(pipeline, config, stats, fp, base, out, data=[])

    def test_tool_action_with_output_does_not_raise(self, pipeline_and_mocks):
        """Tool action producing output should NOT raise."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        pipeline.is_tool_action = True
        data = [{"id": "1"}]
        output = [{"content": {"result": "ok"}}]
        stats = CollectionStats(success=1)

        pipeline.record_processor.process_batch.return_value = []

        with patch(
            "agent_actions.workflow.pipeline.ResultCollector.collect_results",
            return_value=(output, stats),  # non-empty output
        ):
            pipeline.process(fp, base, out, data=data)

        # Should complete normally — output_handler.save_main_output called
        pipeline.output_handler.save_main_output.assert_called_once()


class TestZeroSuccessFailure:
    """Tests for the zero-success failure check.

    When all records fail or exhaust retries (stats.success == 0) and there
    are actual failures (stats.failed + stats.exhausted > 0), the pipeline
    should raise RuntimeError so the executor marks the action as failed
    and the circuit breaker skips downstream dependents.
    """

    def _run_with_stats(self, pipeline, config, stats, fp, base, out, data=None, output=None):
        """Call process() with mocked collect_results."""
        if data is None:
            data = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        if output is None:
            output = data  # default: mock returns input as output

        pipeline.record_processor.process_batch.return_value = []

        with patch(
            "agent_actions.workflow.pipeline.ResultCollector.collect_results",
            return_value=(output, stats),
        ):
            pipeline.process(fp, base, out, data=data)

    def test_all_failed_raises(self, pipeline_and_mocks):
        """All records FAILED with zero output → RuntimeError."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(failed=3)

        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            self._run_with_stats(pipeline, config, stats, fp, base, out, output=[])

    def test_all_exhausted_raises(self, pipeline_and_mocks):
        """All records EXHAUSTED (tombstones in output) → RuntimeError.

        This is the blind spot: EXHAUSTED records produce tombstone data
        that makes the output list non-empty, but zero records actually
        succeeded. The old check (`not output`) missed this.
        """
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(exhausted=3)
        tombstones = [{"_unprocessed": True}] * 3

        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            self._run_with_stats(pipeline, config, stats, fp, base, out, output=tombstones)

    def test_mixed_failed_exhausted_raises(self, pipeline_and_mocks):
        """Mixed FAILED + EXHAUSTED with zero successes → RuntimeError."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(failed=2, exhausted=1)
        tombstones = [{"_unprocessed": True}]

        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            self._run_with_stats(pipeline, config, stats, fp, base, out, output=tombstones)

    def test_error_message_includes_both_counts(self, pipeline_and_mocks):
        """Error message should include both failed and exhausted counts."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(failed=2, exhausted=1)

        with pytest.raises(RuntimeError, match=r"2 failed, 1 exhausted"):
            self._run_with_stats(
                pipeline, config, stats, fp, base, out, output=[{"_unprocessed": True}]
            )

    def test_partial_success_with_failures_no_raise(self, pipeline_and_mocks):
        """Some records succeed + some fail → no raise (partial success is OK)."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(success=1, failed=2)
        output = [{"result": "ok"}]

        # Should not raise — partial success
        self._run_with_stats(pipeline, config, stats, fp, base, out, output=output)

        pipeline.output_handler.save_main_output.assert_called_once()

    def test_partial_success_with_exhausted_no_raise(self, pipeline_and_mocks):
        """Some records succeed + some exhaust → no raise."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(success=2, exhausted=1)
        output = [{"result": "ok"}, {"result": "ok2"}, {"_unprocessed": True}]

        self._run_with_stats(pipeline, config, stats, fp, base, out, output=output)

        pipeline.output_handler.save_main_output.assert_called_once()

    def test_all_deferred_no_raise(self, pipeline_and_mocks):
        """All records deferred (batch queued) → no raise."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(deferred=3)

        self._run_with_stats(pipeline, config, stats, fp, base, out, output=[])

    def test_empty_input_no_raise(self, pipeline_and_mocks):
        """Empty input data → no raise (nothing to fail)."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats()

        self._run_with_stats(pipeline, config, stats, fp, base, out, data=[], output=[])
