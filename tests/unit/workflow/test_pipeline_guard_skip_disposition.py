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
        """DISPOSITION_SKIPPED must NOT be written if any record failed."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(failed=1, skipped=1)

        self._run_with_stats(pipeline, config, stats, fp, base, out)

        config.storage_backend.set_disposition.assert_not_called()

    def test_no_disposition_when_records_exhausted(self, pipeline_and_mocks):
        """DISPOSITION_SKIPPED must NOT be written if records exhausted retries."""
        pipeline, config, fp, base, out = pipeline_and_mocks
        stats = CollectionStats(exhausted=2)

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
