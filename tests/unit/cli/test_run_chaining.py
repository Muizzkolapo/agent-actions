"""Tests for --downstream and --upstream CLI flags.

Covers:
- RunCommandArgs accepts downstream/upstream flags
- RunCommand.execute delegates to _execute_chain when flags are set
- RunCommand._execute_chain resolves plan and calls _execute_single per workflow
- Without flags, execute delegates to _execute_single (existing behavior)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_actions.validation.run_validator import RunCommandArgs


class TestRunCommandArgsFlags:
    """RunCommandArgs accepts downstream/upstream fields."""

    def test_defaults_false(self):
        args = RunCommandArgs(agent="test")
        assert args.downstream is False
        assert args.upstream is False

    def test_downstream_true(self):
        args = RunCommandArgs(agent="test", downstream=True)
        assert args.downstream is True
        assert args.upstream is False

    def test_upstream_true(self):
        args = RunCommandArgs(agent="test", upstream=True)
        assert args.upstream is True
        assert args.downstream is False

    def test_both_true(self):
        args = RunCommandArgs(agent="test", downstream=True, upstream=True)
        assert args.downstream is True
        assert args.upstream is True


class TestRunCommandChaining:
    """RunCommand routes to chain or single execution based on flags."""

    def test_no_flags_calls_execute_single(self):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="test")
        cmd = RunCommand(args)

        with patch.object(cmd, "_execute_single") as mock_single:
            cmd.execute(project_root=Path("/tmp"))

        mock_single.assert_called_once_with(Path("/tmp"))

    def test_downstream_calls_execute_chain(self):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="test", downstream=True)
        cmd = RunCommand(args)

        with patch.object(cmd, "_execute_chain") as mock_chain:
            cmd.execute(project_root=Path("/tmp"))

        mock_chain.assert_called_once_with(Path("/tmp"))

    def test_upstream_calls_execute_chain(self):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="test", upstream=True)
        cmd = RunCommand(args)

        with patch.object(cmd, "_execute_chain") as mock_chain:
            cmd.execute(project_root=Path("/tmp"))

        mock_chain.assert_called_once_with(Path("/tmp"))

    def test_both_flags_calls_execute_chain(self):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="test", downstream=True, upstream=True)
        cmd = RunCommand(args)

        with patch.object(cmd, "_execute_chain") as mock_chain:
            cmd.execute(project_root=Path("/tmp"))

        mock_chain.assert_called_once_with(Path("/tmp"))


class TestExecuteChain:
    """RunCommand._execute_chain resolves plan and executes workflows."""

    def test_downstream_resolves_correct_direction(self, tmp_path):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="ingest", downstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = ["ingest", "enrich"]

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single"),
        ):
            cmd._execute_chain(project_root=tmp_path)

        mock_orchestrator.resolve_execution_plan.assert_called_once_with("ingest", "downstream")

    def test_upstream_resolves_correct_direction(self, tmp_path):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="enrich", upstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = ["ingest", "enrich"]

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single"),
        ):
            cmd._execute_chain(project_root=tmp_path)

        mock_orchestrator.resolve_execution_plan.assert_called_once_with("enrich", "upstream")

    def test_both_flags_resolves_full_direction(self, tmp_path):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="enrich", downstream=True, upstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = ["ingest", "enrich", "analyze"]

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single"),
        ):
            cmd._execute_chain(project_root=tmp_path)

        mock_orchestrator.resolve_execution_plan.assert_called_once_with("enrich", "full")

    def test_chain_executes_each_workflow_in_order(self, tmp_path):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="ingest", downstream=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = ["ingest", "enrich", "analyze"]

        executed_workflows = []

        def track_execute(self_inner, project_root=None):
            executed_workflows.append(self_inner.agent_name)

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "_execute_single", track_execute),
        ):
            cmd._execute_chain(project_root=tmp_path)

        assert executed_workflows == ["ingest", "enrich", "analyze"]

    def test_chain_does_not_pass_flags_to_child_workflows(self, tmp_path):
        from agent_actions.cli.run import RunCommand

        args = RunCommandArgs(agent="ingest", downstream=True, fresh=True)
        cmd = RunCommand(args)

        mock_orchestrator = MagicMock()
        mock_orchestrator.resolve_execution_plan.return_value = ["ingest"]

        created_commands = []
        original_init = RunCommand.__init__

        def capture_init(self_inner, args_inner):
            original_init(self_inner, args_inner)
            created_commands.append(args_inner)

        with (
            patch(
                "agent_actions.workflow.orchestrator.WorkflowOrchestrator",
                return_value=mock_orchestrator,
            ),
            patch.object(RunCommand, "__init__", capture_init),
            patch.object(RunCommand, "_execute_single"),
        ):
            cmd._execute_chain(project_root=tmp_path)

        # The child workflow args should NOT have downstream/upstream flags
        child_args = created_commands[-1]
        assert child_args.downstream is False
        assert child_args.upstream is False
        # But should preserve other flags
        assert child_args.fresh is True
