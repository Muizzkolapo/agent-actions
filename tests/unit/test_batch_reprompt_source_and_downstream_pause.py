"""Tests for spec 046: reprompt batch source.* resolution + downstream pause gating.

Bug 1: Reprompt batch fails because source_data is not passed to prepare_tasks().
Bug 2: --downstream launches downstream workflows when parent is paused for batch.
"""

from unittest.mock import MagicMock, patch

from agent_actions.validation.run_validator import RunCommandArgs

# ---------------------------------------------------------------------------
# Bug 1: _load_source_data_for_reprompt
# ---------------------------------------------------------------------------


class TestLoadSourceDataForReprompt:
    """_load_source_data_for_reprompt loads source records from the storage backend."""

    def test_returns_records_from_storage_backend(self):
        from agent_actions.llm.batch.services.reprompt_ops import (
            _load_source_data_for_reprompt,
        )

        backend = MagicMock()
        backend.list_source_files.return_value = ["staging/workflow_a"]
        backend.read_source.return_value = [
            {"source_guid": "g1", "page_content": "hello"},
            {"source_guid": "g2", "page_content": "world"},
        ]

        result = _load_source_data_for_reprompt(backend)

        assert result is not None
        assert len(result) == 2
        assert result[0]["page_content"] == "hello"
        backend.read_source.assert_called_once_with("staging/workflow_a")

    def test_merges_multiple_source_files(self):
        from agent_actions.llm.batch.services.reprompt_ops import (
            _load_source_data_for_reprompt,
        )

        backend = MagicMock()
        backend.list_source_files.return_value = ["staging/a", "staging/b"]
        backend.read_source.side_effect = [
            [{"source_guid": "g1"}],
            [{"source_guid": "g2"}],
        ]

        result = _load_source_data_for_reprompt(backend)

        assert result is not None
        assert len(result) == 2

    def test_returns_none_when_backend_is_none(self):
        from agent_actions.llm.batch.services.reprompt_ops import (
            _load_source_data_for_reprompt,
        )

        assert _load_source_data_for_reprompt(None) is None

    def test_returns_none_when_no_source_files(self):
        from agent_actions.llm.batch.services.reprompt_ops import (
            _load_source_data_for_reprompt,
        )

        backend = MagicMock()
        backend.list_source_files.return_value = []

        assert _load_source_data_for_reprompt(backend) is None

    def test_skips_missing_source_files(self):
        from agent_actions.llm.batch.services.reprompt_ops import (
            _load_source_data_for_reprompt,
        )

        backend = MagicMock()
        backend.list_source_files.return_value = ["missing", "exists"]
        backend.read_source.side_effect = [
            FileNotFoundError("gone"),
            [{"source_guid": "g1"}],
        ]

        result = _load_source_data_for_reprompt(backend)

        assert result is not None
        assert len(result) == 1

    def test_returns_none_on_unexpected_error(self):
        from agent_actions.llm.batch.services.reprompt_ops import (
            _load_source_data_for_reprompt,
        )

        backend = MagicMock()
        backend.list_source_files.side_effect = RuntimeError("boom")

        assert _load_source_data_for_reprompt(backend) is None


# ---------------------------------------------------------------------------
# Bug 1: source_data forwarded to prepare_tasks in both reprompt paths
# ---------------------------------------------------------------------------


class TestRepromptPassesSourceData:
    """Both sync and async reprompt paths pass source_data to the preparator."""

    @patch("agent_actions.llm.batch.services.reprompt_ops._load_source_data_for_reprompt")
    @patch("agent_actions.llm.batch.processing.preparator.BatchTaskPreparator")
    def test_submit_reprompt_batch_passes_source_data(self, MockPreparator, mock_load):
        """submit_reprompt_batch passes loaded source_data to prepare_tasks."""
        from agent_actions.llm.batch.services.reprompt_ops import submit_reprompt_batch
        from agent_actions.llm.providers.batch_base import BatchResult

        fake_source = [{"source_guid": "g1", "page_content": "data"}]
        mock_load.return_value = fake_source

        mock_prep_instance = MockPreparator.return_value
        mock_prepared = MagicMock()
        mock_prepared.tasks = [{"target_id": "t1", "prompt": "p"}]
        mock_prep_instance.prepare_tasks.return_value = mock_prepared

        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_123", "submitted")

        failed = [BatchResult(custom_id="t1", content="bad", success=True)]
        context_map = {"t1": {"content": {"q": "a"}, "source_guid": "g1"}}

        agent_config = {
            "reprompt": {"validation": "check_it", "max_attempts": 2},
            "name": "test_action",
        }

        with (
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(lambda x: False, "fix it"),
            ),
            patch(
                "agent_actions.processing.recovery.response_validator.build_validation_feedback",
                return_value="feedback",
            ),
            patch(
                "agent_actions.processing.recovery.response_validator.resolve_feedback_strategies",
                return_value=[],
            ),
            patch(
                "agent_actions.processing.recovery.reprompt.parse_reprompt_config",
            ) as mock_parse,
        ):
            mock_parse.return_value = MagicMock(
                validation_name="check_it", max_attempts=2, on_exhausted="return_last"
            )
            result = submit_reprompt_batch(
                action_indices={},
                dependency_configs={},
                storage_backend=MagicMock(),
                provider=provider,
                failed_results=failed,
                context_map=context_map,
                output_directory="/tmp/out",
                file_name="batch_1",
                agent_config=agent_config,
                attempt=1,
            )

        assert result is not None
        # Verify source_data was passed to prepare_tasks
        prep_call = mock_prep_instance.prepare_tasks.call_args
        assert prep_call.kwargs.get("source_data") is fake_source

    @patch("agent_actions.llm.batch.services.reprompt_ops._load_source_data_for_reprompt")
    @patch("agent_actions.llm.batch.processing.preparator.BatchTaskPreparator")
    def test_validate_and_reprompt_passes_source_data(self, MockPreparator, mock_load):
        """validate_and_reprompt passes loaded source_data to prepare_tasks."""
        from agent_actions.llm.batch.services.reprompt_ops import validate_and_reprompt
        from agent_actions.llm.providers.batch_base import BatchResult

        fake_source = [{"source_guid": "g1", "page_content": "data"}]
        mock_load.return_value = fake_source

        mock_prep_instance = MockPreparator.return_value
        mock_prepared = MagicMock()
        mock_prepared.tasks = [{"target_id": "t1", "prompt": "p"}]
        mock_prep_instance.prepare_tasks.return_value = mock_prepared

        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_123", "submitted")
        provider.retrieve_results.return_value = [
            BatchResult(custom_id="t1", content="good", success=True)
        ]

        failed_result = BatchResult(custom_id="t1", content="bad", success=True)
        context_map = {"t1": {"content": {"q": "a"}, "source_guid": "g1"}}

        agent_config = {
            "reprompt": {"validation": "check_it", "max_attempts": 2},
            "name": "test_action",
        }

        call_count = 0

        def validation_func(content):
            nonlocal call_count
            call_count += 1
            return call_count > 1  # Fail first, pass second

        with (
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(validation_func, "fix it"),
            ),
            patch(
                "agent_actions.llm.batch.services.retry_polling.wait_for_batch_completion",
                return_value="completed",
            ),
        ):
            validate_and_reprompt(
                action_indices={},
                dependency_configs={},
                storage_backend=MagicMock(),
                results=[failed_result],
                provider=provider,
                context_map=context_map,
                output_directory="/tmp/out",
                file_name="batch_1",
                agent_config=agent_config,
            )

        # Verify source_data was passed to prepare_tasks
        prep_call = mock_prep_instance.prepare_tasks.call_args
        assert prep_call.kwargs.get("source_data") is fake_source


# ---------------------------------------------------------------------------
# Bug 2: downstream deferred during batch pause
# ---------------------------------------------------------------------------


class TestExecuteChainBatchPauseGating:
    """_execute_chain defers downstream workflows when parent is PAUSED."""

    def test_defers_downstream_when_parent_paused(self, tmp_path):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="parent_wf", downstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = [
            "parent_wf",
            "child_wf",
            "grandchild_wf",
        ]

        executed = []

        def mock_execute_single(self_inner, project_root=None):
            executed.append(self_inner.agent_name)
            return "PAUSED"

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single", mock_execute_single),
        ):
            cmd._execute_chain(project_root=tmp_path)

        # Only the first workflow should have executed
        assert executed == ["parent_wf"]

    def test_prints_deferral_messages(self, tmp_path, capsys):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="parent_wf", downstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = [
            "parent_wf",
            "child_wf",
            "grandchild_wf",
        ]

        def mock_execute_single(self_inner, project_root=None):
            return "PAUSED"

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single", mock_execute_single),
        ):
            cmd._execute_chain(project_root=tmp_path)

        output = capsys.readouterr().out
        assert "Downstream workflow 'child_wf' deferred" in output
        assert "Downstream workflow 'grandchild_wf' deferred" in output
        assert "waiting for parent batch to complete" in output

    def test_continues_downstream_when_parent_succeeds(self, tmp_path):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="parent_wf", downstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = [
            "parent_wf",
            "child_wf",
            "grandchild_wf",
        ]

        executed = []

        def mock_execute_single(self_inner, project_root=None):
            executed.append(self_inner.agent_name)
            return "SUCCESS"

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single", mock_execute_single),
        ):
            cmd._execute_chain(project_root=tmp_path)

        assert executed == ["parent_wf", "child_wf", "grandchild_wf"]

    def test_paused_mid_chain_defers_remaining(self, tmp_path):
        """When the second workflow pauses, only the third is deferred."""
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="wf_a", downstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = ["wf_a", "wf_b", "wf_c"]

        executed = []
        statuses = iter(["SUCCESS", "PAUSED"])

        def mock_execute_single(self_inner, project_root=None):
            executed.append(self_inner.agent_name)
            return next(statuses)

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single", mock_execute_single),
        ):
            cmd._execute_chain(project_root=tmp_path)

        assert executed == ["wf_a", "wf_b"]

    def test_no_deferral_when_last_workflow_pauses(self, tmp_path, capsys):
        """No deferral message when the last workflow in the chain pauses."""
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="only_wf", downstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = ["only_wf"]

        def mock_execute_single(self_inner, project_root=None):
            return "PAUSED"

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single", mock_execute_single),
        ):
            cmd._execute_chain(project_root=tmp_path)

        output = capsys.readouterr().out
        assert "deferred" not in output
