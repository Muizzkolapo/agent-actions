"""
Test prompt preparation parity between batch and online modes.

Tests for issue #801: Prompt Preparation Divergences
- workflow_metadata in batch mode (previously missing)
- tools_path in online mode (previously missing)
"""

import pytest


class TestBatchModeWorkflowMetadata:
    """Verify batch mode accepts and passes workflow_metadata."""

    def test_prepare_tasks_accepts_workflow_metadata(self):
        """Verify prepare_tasks signature includes workflow_metadata parameter."""
        from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
        import inspect

        sig = inspect.signature(BatchTaskPreparator.prepare_tasks)
        params = list(sig.parameters.keys())

        assert "workflow_metadata" in params, \
            "prepare_tasks should accept workflow_metadata parameter"

    def test_prepare_tasks_passes_workflow_metadata_to_service(self):
        """Verify workflow_metadata flows through to PromptPreparationService."""
        from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
        import inspect

        # Check _prepare_single_task accepts workflow_metadata
        sig = inspect.signature(BatchTaskPreparator._prepare_single_task)
        params = list(sig.parameters.keys())

        assert "workflow_metadata" in params, \
            "_prepare_single_task should accept workflow_metadata parameter"

    def test_submission_service_accepts_workflow_metadata(self):
        """Verify BatchSubmissionService.prepare_batch_tasks accepts workflow_metadata."""
        from agent_actions.llm.batch.services.submission import BatchSubmissionService
        import inspect

        sig = inspect.signature(BatchSubmissionService.prepare_batch_tasks)
        params = list(sig.parameters.keys())

        assert "workflow_metadata" in params, \
            "prepare_batch_tasks should accept workflow_metadata parameter"

    def test_submit_batch_job_accepts_workflow_metadata(self):
        """Verify BatchSubmissionService.submit_batch_job accepts workflow_metadata."""
        from agent_actions.llm.batch.services.submission import BatchSubmissionService
        import inspect

        sig = inspect.signature(BatchSubmissionService.submit_batch_job)
        params = list(sig.parameters.keys())

        assert "workflow_metadata" in params, \
            "submit_batch_job should accept workflow_metadata parameter"


class TestOnlineModeToolsPath:
    """Verify online mode resolves and passes tools_path."""

    def test_prepare_prompt_resolves_tools_path(self):
        """Verify _prepare_prompt resolves tools_path from agent_config."""
        from agent_actions.processing.processor import RecordProcessor
        import inspect

        source = inspect.getsource(RecordProcessor._prepare_prompt)

        # Should import resolve_tools_path
        assert "resolve_tools_path" in source, \
            "_prepare_prompt should import resolve_tools_path"

        # Should call resolve_tools_path
        assert "resolve_tools_path(context.agent_config)" in source, \
            "_prepare_prompt should resolve tools_path from agent_config"

        # Should pass tools_path to service
        assert "tools_path=tools_path" in source, \
            "_prepare_prompt should pass tools_path to PromptPreparationService"


class TestPromptPreparationServiceParity:
    """Verify both modes pass the same parameters to PromptPreparationService."""

    def test_batch_and_online_pass_same_core_parameters(self):
        """Verify both modes pass the same core parameters."""
        from agent_actions.processing.processor import RecordProcessor
        from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
        import inspect

        online_source = inspect.getsource(RecordProcessor._prepare_prompt)
        batch_source = inspect.getsource(BatchTaskPreparator._prepare_single_task)

        # Both should pass these core parameters
        core_params = [
            "agent_config=",
            "agent_name=",
            "contents=",
            "mode=",
            "agent_indices=",
            "dependency_configs=",
            "source_content=",
            "current_item=",
            "file_path=",
            "tools_path=",
        ]

        for param in core_params:
            assert param in online_source, \
                f"Online mode should pass {param.rstrip('=')} to PromptPreparationService"
            assert param in batch_source, \
                f"Batch mode should pass {param.rstrip('=')} to PromptPreparationService"

    def test_online_has_loop_context_batch_does_not(self):
        """Verify online has loop_context (expected architectural difference)."""
        from agent_actions.processing.processor import RecordProcessor
        from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
        import inspect

        online_source = inspect.getsource(RecordProcessor._prepare_prompt)
        batch_source = inspect.getsource(BatchTaskPreparator._prepare_single_task)

        # Online mode has loop_context (for loop iteration context)
        assert "loop_context=" in online_source, \
            "Online mode should pass loop_context"

        # Batch mode doesn't have loop_context (prepares all tasks upfront)
        # This is an expected architectural difference
        # Batch mode could pass workflow_metadata instead
        assert "workflow_metadata=" in batch_source, \
            "Batch mode should pass workflow_metadata"


class TestPipelineParamsIncludeWorkflowMetadata:
    """Verify pipeline params include workflow_metadata for batch mode."""

    def test_batch_pipeline_params_has_workflow_metadata(self):
        """Verify BatchPipelineParams has workflow_metadata field."""
        from agent_actions.workflow.pipeline import BatchPipelineParams
        import dataclasses

        fields = {f.name for f in dataclasses.fields(BatchPipelineParams)}
        assert "workflow_metadata" in fields, \
            "BatchPipelineParams should have workflow_metadata field"

    def test_process_params_has_workflow_metadata(self):
        """Verify ProcessParams has workflow_metadata field."""
        from agent_actions.workflow.pipeline import ProcessParams
        import dataclasses

        fields = {f.name for f in dataclasses.fields(ProcessParams)}
        assert "workflow_metadata" in fields, \
            "ProcessParams should have workflow_metadata field"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
