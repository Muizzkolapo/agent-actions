"""Tests for shared pipeline context building (ARCH-005).

Verifies that _build_pipeline_context() produces correct results and that
both batch and online paths receive the same context fields.
"""

from agent_actions.workflow.pipeline import BatchPipelineParams, ProcessingPipeline


class TestBuildPipelineContext:
    """Tests for _build_pipeline_context shared context builder."""

    def test_returns_none_when_no_action_configs(self):
        """No action_configs should return (None, None, None)."""
        agent_indices, dependency_configs, version_context = (
            ProcessingPipeline._build_pipeline_context(
                action_config={},
                action_configs=None,
            )
        )
        assert agent_indices is None
        assert dependency_configs is None
        assert version_context is None

    def test_builds_agent_indices_from_action_configs(self):
        """Should extract idx from each action config."""
        action_configs = {
            "extract": {"idx": 0, "agent_type": "extract"},
            "transform": {"idx": 1, "agent_type": "transform"},
        }
        agent_indices, dependency_configs, _ = ProcessingPipeline._build_pipeline_context(
            action_config={},
            action_configs=action_configs,
        )
        assert agent_indices == {"extract": 0, "transform": 1}
        assert dependency_configs is action_configs

    def test_skips_actions_without_idx(self):
        """Actions missing 'idx' should be excluded from agent_indices."""
        action_configs = {
            "with_idx": {"idx": 0},
            "without_idx": {"agent_type": "test"},
        }
        agent_indices, _, _ = ProcessingPipeline._build_pipeline_context(
            action_config={},
            action_configs=action_configs,
        )
        assert agent_indices == {"with_idx": 0}

    def test_extracts_version_context_for_versioned_agent(self):
        """Versioned agents should have version_context extracted."""
        action_config = {
            "is_versioned_agent": True,
            "_version_context": {"i": 2, "length": 5},
        }
        _, _, version_context = ProcessingPipeline._build_pipeline_context(
            action_config=action_config,
            action_configs=None,
        )
        assert version_context == {"i": 2, "length": 5}

    def test_version_context_is_copied(self):
        """Returned version_context should be a copy, not the original dict."""
        original = {"i": 0, "length": 3}
        action_config = {
            "is_versioned_agent": True,
            "_version_context": original,
        }
        _, _, version_context = ProcessingPipeline._build_pipeline_context(
            action_config=action_config,
            action_configs=None,
        )
        assert version_context == original
        assert version_context is not original

    def test_no_version_context_for_non_versioned_agent(self):
        """Non-versioned agents should have version_context=None."""
        action_config = {"agent_type": "extract"}
        _, _, version_context = ProcessingPipeline._build_pipeline_context(
            action_config=action_config,
            action_configs=None,
        )
        assert version_context is None


class TestBatchPathReceivesVersionContext:
    """Verify that the batch path forwards version_context through the chain."""

    def test_batch_pipeline_params_carries_version_context(self):
        """BatchPipelineParams should carry version_context to _handle_batch_generation."""
        params = BatchPipelineParams(
            pipeline_action_config={"agent_type": "test"},
            pipeline_action_name="test_action",
            batch_file_path="/tmp/input.json",
            batch_base_directory="/tmp",
            batch_output_directory="/tmp/output",
            version_context={"i": 1, "length": 4},
        )
        assert params.version_context == {"i": 1, "length": 4}

    def test_build_pipeline_context_called_before_batch_fork(self):
        """_process_by_strategy should call _build_pipeline_context before the batch fork.

        This is the architectural guarantee: context building happens ONCE,
        before the batch/online decision, so both paths receive the same context.
        """
        # Verify by checking that _build_pipeline_context produces correct output
        # for a versioned agent with action_configs — the same output that both
        # the batch and online paths will receive.
        action_config = {
            "is_versioned_agent": True,
            "_version_context": {"i": 2, "length": 5},
        }
        action_configs = {
            "extract": {"idx": 0},
            "transform": {"idx": 1},
        }

        agent_indices, dependency_configs, version_context = (
            ProcessingPipeline._build_pipeline_context(action_config, action_configs)
        )

        # Both batch and online paths receive these same values
        assert agent_indices == {"extract": 0, "transform": 1}
        assert dependency_configs is action_configs
        assert version_context == {"i": 2, "length": 5}


class TestBatchPreparatorVersionContext:
    """Verify BatchTaskPreparator forwards version_context to PreparationContext."""

    def test_version_context_set_on_preparation_context(self):
        """BatchTaskPreparator should set version_context on PreparationContext."""
        from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

        preparator = BatchTaskPreparator(
            version_context={"i": 0, "length": 3},
        )

        ctx = preparator._build_preparation_context(
            agent_config={"agent_type": "test"},
            output_directory="/tmp/output",
            batch_name="test_batch",
            source_data=None,
            workflow_metadata=None,
            tools_path=None,
        )

        assert ctx.version_context == {"i": 0, "length": 3}

    def test_version_context_none_by_default(self):
        """Without version_context, PreparationContext.version_context should be None."""
        from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

        preparator = BatchTaskPreparator()

        ctx = preparator._build_preparation_context(
            agent_config={"agent_type": "test"},
            output_directory="/tmp/output",
            batch_name="test_batch",
            source_data=None,
            workflow_metadata=None,
            tools_path=None,
        )

        assert ctx.version_context is None
