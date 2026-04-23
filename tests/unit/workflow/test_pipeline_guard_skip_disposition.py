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

    def _run_with_stats(
        self, pipeline, config, stats, file_path, base_dir, output_dir, data=None, output=None
    ):
        """Call process() with mocked collect_results stats.

        Args:
            output: The output list returned by collect_results. Defaults to
                ``data`` (simulating passthrough). Pass ``[]`` to simulate
                filtered records that produce no output.
        """
        if data is None:
            data = [{"id": "1"}, {"id": "2"}]
        if output is None:
            output = data

        pipeline.record_processor.process_batch.return_value = []

        with patch(
            "agent_actions.workflow.pipeline.ResultCollector.collect_results",
            return_value=(output, stats),
        ):
            pipeline.process(file_path, base_dir, output_dir, data=data)

    def test_no_disposition_when_all_guard_skipped_with_output(self, pipeline_and_mocks):
        """Guard-skipped records ARE in output — no node-level skip, downstream proceeds."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(skipped=2)

        self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_not_called()

    def test_writes_disposition_when_all_filtered(self, pipeline_and_mocks):
        """All-filtered produces empty output — node-level skip blocks downstream."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(filtered=2)

        self._run_with_stats(pipeline, config, stats, fp, base, out, output=[])

        config.storage_backend.set_disposition.assert_called_once_with(
            "test_action",
            NODE_LEVEL_RECORD_ID,
            DISPOSITION_SKIPPED,
            reason="All records filtered — no output produced",
        )

    def test_no_disposition_when_all_unprocessed_with_output(self, pipeline_and_mocks):
        """Unprocessed records ARE in output — no node-level skip."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(unprocessed=2)

        self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_not_called()

    def test_no_disposition_when_all_unprocessed_empty_data(self, pipeline_and_mocks):
        """Bug #10: UNPROCESSED with empty data → empty output, but must NOT trigger SKIPPED.

        Records were unprocessed (not filtered). The disposition condition must
        check stats.unprocessed to avoid falsely writing SKIPPED.
        """
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(unprocessed=5)

        self._run_with_stats(pipeline, config, stats, fp, base, out, output=[])

        config.storage_backend.set_disposition.assert_not_called()

    def test_no_disposition_when_mixed_skip_filter_with_output(self, pipeline_and_mocks):
        """Mixed skip+filter: skipped records produce output, so no cascade-block."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(skipped=1, filtered=1)

        self._run_with_stats(pipeline, config, stats, fp, base, out, output=[{"id": "1"}])

        config.storage_backend.set_disposition.assert_not_called()

    def test_writes_disposition_when_skipped_data_is_empty(self, pipeline_and_mocks):
        """Guard-skipped records with empty data produce empty output — cascade-block."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(skipped=2)

        self._run_with_stats(pipeline, config, stats, fp, base, out, output=[])

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
        stats = CollectionStats(filtered=2)

        # Should not raise — empty output enters the block, but backend is None
        self._run_with_stats(pipeline, config, stats, fp, base, out, output=[])

    def test_storage_error_is_logged_not_raised(self, pipeline_and_mocks):
        """Storage errors during disposition write should be logged, not propagated."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        config.storage_backend.set_disposition.side_effect = RuntimeError("DB error")
        stats = CollectionStats(filtered=2)

        # Should not raise — empty output enters the block, storage error is caught
        self._run_with_stats(pipeline, config, stats, fp, base, out, output=[])


class TestToolActionEmptyOutputUsesGenericPath:
    """Tool actions with empty output flow through the generic zero-success
    check via ProcessingResult.failed() — no tool-specific branch needed.
    """

    def test_tool_failed_result_triggers_zero_success_check(self, pipeline_and_mocks):
        """Tool empty output (stats.failed=1, success=0) triggers the generic check."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        pipeline.is_tool_action = True
        stats = CollectionStats(failed=1)

        pipeline.record_processor.process_batch.return_value = []
        with patch(
            "agent_actions.workflow.pipeline.ResultCollector.collect_results",
            return_value=([], stats),
        ):
            with pytest.raises(RuntimeError, match="produced 0 successful records"):
                pipeline.process(fp, base, out, data=[{"id": "1"}])


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

        with pytest.raises(RuntimeError, match="failed or exhausted"):
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


class TestZeroSuccessWithRealResults:
    """Integration tests using real ProcessingResult objects through ResultCollector.

    These tests do NOT mock collect_results — they send real ProcessingResult
    objects through the actual collection pipeline to verify the full chain:
    process_batch returns results → collect_results produces stats → pipeline
    check raises RuntimeError.
    """

    def test_all_exhausted_real_results_raises(self, pipeline_and_mocks):
        """Real EXHAUSTED ProcessingResults through actual collect_results → RuntimeError."""
        from agent_actions.processing.types import ProcessingResult

        pipeline, config, fp, base, out = pipeline_and_mocks
        config.action_config = {"kind": "llm"}

        exhausted_results = [
            ProcessingResult.exhausted(
                "timeout after 3 attempts",
                data=[{"_unprocessed": True, "source_guid": f"guid_{i}"}],
                source_guid=f"guid_{i}",
            )
            for i in range(3)
        ]

        pipeline.record_processor.process_batch.return_value = exhausted_results

        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            pipeline.process(fp, base, out, data=[{"id": "1"}, {"id": "2"}, {"id": "3"}])

    def test_all_failed_real_results_raises(self, pipeline_and_mocks):
        """Real FAILED ProcessingResults through actual collect_results → RuntimeError."""
        from agent_actions.processing.types import ProcessingResult

        pipeline, config, fp, base, out = pipeline_and_mocks
        config.action_config = {"kind": "llm"}

        failed_results = [
            ProcessingResult.failed(
                "Error code: 401 - Invalid API Key",
                source_guid=f"guid_{i}",
            )
            for i in range(3)
        ]

        pipeline.record_processor.process_batch.return_value = failed_results

        with pytest.raises(RuntimeError, match="produced 0 successful records"):
            pipeline.process(fp, base, out, data=[{"id": "1"}, {"id": "2"}, {"id": "3"}])

    def test_mixed_real_results_raises(self, pipeline_and_mocks):
        """Mixed FAILED + EXHAUSTED real results → RuntimeError."""
        from agent_actions.processing.types import ProcessingResult

        pipeline, config, fp, base, out = pipeline_and_mocks
        config.action_config = {"kind": "llm"}

        results = [
            ProcessingResult.failed("401 Unauthorized", source_guid="guid_0"),
            ProcessingResult.failed("401 Unauthorized", source_guid="guid_1"),
            ProcessingResult.exhausted(
                "timeout after 3 attempts",
                data=[{"_unprocessed": True}],
                source_guid="guid_2",
            ),
        ]

        pipeline.record_processor.process_batch.return_value = results

        with pytest.raises(RuntimeError, match=r"2 failed, 1 exhausted"):
            pipeline.process(fp, base, out, data=[{"id": "1"}, {"id": "2"}, {"id": "3"}])

    def test_partial_success_real_results_no_raise(self, pipeline_and_mocks):
        """Mix of SUCCESS + FAILED real results → no raise (partial success)."""
        from agent_actions.processing.types import ProcessingResult, ProcessingStatus

        pipeline, config, fp, base, out = pipeline_and_mocks
        config.action_config = {"kind": "llm"}

        results = [
            ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                data=[{"result": "ok", "source_guid": "guid_0"}],
                executed=True,
                source_guid="guid_0",
            ),
            ProcessingResult.failed("401 Unauthorized", source_guid="guid_1"),
        ]

        pipeline.record_processor.process_batch.return_value = results
        pipeline.process(fp, base, out, data=[{"id": "1"}, {"id": "2"}])

        pipeline.output_handler.save_main_output.assert_called_once()
