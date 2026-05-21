"""Tests for staging batch pipeline parity (spec 422).

Verifies that batch first-stage processing receives the same pipeline context
as downstream batch: agent_indices, dependency_configs, version_context,
source_data, and workflow_metadata.
"""

import json
from unittest.mock import patch

import pytest

from agent_actions.input.preprocessing.staging.initial_pipeline import (
    BatchProcessingContext,
    _process_batch_mode,
)
from agent_actions.llm.batch.core.batch_models import SubmissionResult

_PREP_MODULE = "agent_actions.llm.batch.processing.preparator"
_SUBMISSION_MODULE = "agent_actions.llm.batch.services.submission"


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


@pytest.fixture
def action_configs():
    """Multi-action pipeline configs with idx ordering."""
    return {
        "extract": {"idx": 0, "model_vendor": "openai"},
        "classify": {"idx": 1, "model_vendor": "openai"},
        "summarize": {"idx": 2, "model_vendor": "openai"},
    }


def _make_ctx(tmp_dirs, *, action_configs=None, agent_config=None, data_chunk=None):
    """Build a BatchProcessingContext for testing."""
    base, output, input_file = tmp_dirs
    return BatchProcessingContext(
        agent_config=agent_config or {"run_mode": "batch"},
        agent_name="extract",
        data_chunk=data_chunk or [{"batch_id": "b1", "batch_uuid": "b1_0", "content": "x"}],
        file_path=str(input_file),
        base_directory=str(base),
        output_directory=str(output),
        action_configs=action_configs,
    )


class TestBatchFirstStagePipelineContext:
    """BatchTaskPreparator receives full pipeline context from _build_pipeline_context."""

    def test_preparator_receives_agent_indices_and_dependency_configs(
        self, tmp_dirs, action_configs
    ):
        """When action_configs is provided, BatchTaskPreparator gets agent_indices
        and dependency_configs — matching the downstream batch path."""
        ctx = _make_ctx(tmp_dirs, action_configs=action_configs)

        with (
            patch(f"{_PREP_MODULE}.BatchTaskPreparator") as MockPrep,
            patch(f"{_SUBMISSION_MODULE}.BatchSubmissionService") as MockSvc,
        ):
            MockSvc.return_value.submit_batch_job.return_value = SubmissionResult(
                batch_id="vid_123"
            )
            _process_batch_mode(ctx)

        prep_kwargs = MockPrep.call_args[1]
        assert prep_kwargs["action_indices"] == {"extract": 0, "classify": 1, "summarize": 2}
        assert prep_kwargs["dependency_configs"] is action_configs

    def test_preparator_receives_version_context_for_versioned_agent(
        self, tmp_dirs, action_configs
    ):
        """Versioned agents get version_context threaded to BatchTaskPreparator."""
        version_ctx = {"version_id": "v42", "base_version": "v41"}
        ctx = _make_ctx(
            tmp_dirs,
            action_configs=action_configs,
            agent_config={
                "run_mode": "batch",
                "is_versioned_agent": True,
                "_version_context": version_ctx,
            },
        )

        with (
            patch(f"{_PREP_MODULE}.BatchTaskPreparator") as MockPrep,
            patch(f"{_SUBMISSION_MODULE}.BatchSubmissionService") as MockSvc,
        ):
            MockSvc.return_value.submit_batch_job.return_value = SubmissionResult(
                batch_id="vid_123"
            )
            _process_batch_mode(ctx)

        prep_kwargs = MockPrep.call_args[1]
        assert prep_kwargs["version_context"] == version_ctx
        # Must be a copy, not the same object (mutation safety from _build_pipeline_context)
        assert prep_kwargs["version_context"] is not version_ctx

    def test_preparator_accepts_none_action_configs(self, tmp_dirs):
        """When action_configs is None (single-action workflow), preparator gets
        None for indices/configs — matches _build_pipeline_context contract."""
        ctx = _make_ctx(tmp_dirs)  # action_configs defaults to None

        with (
            patch(f"{_PREP_MODULE}.BatchTaskPreparator") as MockPrep,
            patch(f"{_SUBMISSION_MODULE}.BatchSubmissionService") as MockSvc,
        ):
            MockSvc.return_value.submit_batch_job.return_value = SubmissionResult(
                batch_id="vid_123"
            )
            _process_batch_mode(ctx)

        prep_kwargs = MockPrep.call_args[1]
        assert prep_kwargs["action_indices"] is None
        assert prep_kwargs["dependency_configs"] is None
        assert prep_kwargs["version_context"] is None


class TestBatchFirstStageTemplateContext:
    """submit_batch_job receives source_data and workflow_metadata for template rendering."""

    def test_submit_receives_source_data_and_workflow_metadata(self, tmp_dirs):
        """source_data and workflow_metadata are passed to submit_batch_job so
        {{ source.* }} and {{ workflow.* }} templates resolve."""
        data_chunk = [{"batch_id": "b1", "batch_uuid": "b1_0", "name": "Alice"}]
        base, output, input_file = tmp_dirs
        ctx = _make_ctx(tmp_dirs, data_chunk=data_chunk)

        with patch(f"{_SUBMISSION_MODULE}.BatchSubmissionService") as MockSvc:
            mock_submit = MockSvc.return_value.submit_batch_job
            mock_submit.return_value = SubmissionResult(batch_id="vid_123")
            _process_batch_mode(ctx)

        _, kwargs = mock_submit.call_args
        assert kwargs["source_data"] is data_chunk
        assert kwargs["workflow_metadata"] == {"source_file": str(input_file)}

    def test_submit_positional_args_unchanged(self, tmp_dirs):
        """Positional args (agent_config, batch_name, data, output_directory)
        remain in the same order — no regression."""
        base, output, input_file = tmp_dirs
        data_chunk = [{"batch_id": "b1", "batch_uuid": "b1_0", "content": "x"}]
        ctx = _make_ctx(tmp_dirs, data_chunk=data_chunk)

        with patch(f"{_SUBMISSION_MODULE}.BatchSubmissionService") as MockSvc:
            mock_submit = MockSvc.return_value.submit_batch_job
            mock_submit.return_value = SubmissionResult(batch_id="vid_123")
            _process_batch_mode(ctx)

        args, _ = mock_submit.call_args
        assert args[0] == {"run_mode": "batch"}  # agent_config
        assert args[1] == "sample.json"  # batch_name (file_name)
        assert args[2] is data_chunk  # data
        assert args[3] == str(output)  # output_directory


class TestInitialStrategyThreadsActionConfigs:
    """InitialStrategy passes action_configs from StrategyExecutionParams
    to InitialStageContext, which threads to BatchProcessingContext."""

    def test_action_configs_threaded_to_initial_stage_context(self):
        """StrategyExecutionParams.action_configs reaches InitialStageContext."""
        from agent_actions.workflow.strategies import InitialStrategy, StrategyExecutionParams

        action_configs = {"a": {"idx": 0}, "b": {"idx": 1}}

        captured_ctx = {}

        # Patch where strategies.py imported the function (its own namespace)
        with patch("agent_actions.workflow.strategies.process_initial_stage") as mock_process:

            def capture(ctx):
                captured_ctx["action_configs"] = ctx.action_configs
                return "/fake/path.json"

            mock_process.side_effect = capture

            strategy = InitialStrategy()
            strategy.execute(
                StrategyExecutionParams(
                    action_config={"run_mode": "batch"},
                    action_name="test",
                    file_path="/fake/input.json",
                    base_directory="/fake/base",
                    output_directory="/fake/output",
                    idx=0,
                    action_configs=action_configs,
                )
            )

        assert captured_ctx["action_configs"] is action_configs
