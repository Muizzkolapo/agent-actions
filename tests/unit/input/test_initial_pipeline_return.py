"""Tests for initial pipeline return contract (P1 #1).

Both _process_batch_mode() and _process_online_mode_with_record_processor()
must return a string path to the output file.
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
                "agent_actions.input.preprocessing.staging.initial_pipeline.RecordProcessor"
            ) as MockProc,
            patch(
                "agent_actions.input.preprocessing.staging.initial_pipeline.ResultCollector"
            ) as MockCollector,
            patch("agent_actions.input.preprocessing.staging.initial_pipeline.FileWriter"),
        ):
            MockProc.return_value.process_batch.return_value = [{"result": "ok"}]
            from agent_actions.processing.result_collector import CollectionStats

            MockCollector.collect_results.return_value = (
                [{"result": "ok"}],
                CollectionStats(success=1),
            )

            result = _process_online_mode_with_record_processor(
                data_chunk, ctx, str(input_file), str(base), str(output)
            )

        assert isinstance(result, str)
        assert result.endswith(".json")
