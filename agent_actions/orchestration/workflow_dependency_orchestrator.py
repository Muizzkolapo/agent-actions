# pylint: disable=duplicate-code
"""
Workflow dependency orchestration for upstream/downstream execution.

This module handles recursive execution of dependent workflows,
coordinating upstream dependencies before and downstream workflows after
the main workflow completes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from agent_actions.logging import CorrelationContext
from agent_actions.orchestration.artifact_linker import ArtifactLinker
from agent_actions.orchestration.workspace_index import WorkspaceIndex

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


class WorkflowDependencyOrchestrator:
    """
    Orchestrates upstream and downstream workflow dependencies.

    Handles recursive execution of dependent workflows, status checking,
    and artifact linking between workflows.
    """

    def __init__(
        self,
        workflows_root: Path,
        current_workflow: str,
        console: Console,
        workflow_factory: Callable[..., Any]
    ):
        """
        Initialize the dependency orchestrator.

        Args:
            workflows_root: Root directory containing all workflows.
            current_workflow: Name of the current workflow being executed.
            console: Rich console for output.
            workflow_factory: Callable to create new workflow instances.
                              Signature: (config_path, user_code_path, default_path,
                                         use_tools, run_upstream, run_downstream) -> workflow
        """
        self.workflows_root = workflows_root
        self.current_workflow = current_workflow
        self.console = console
        self.workflow_factory = workflow_factory
        self.artifact_linker = ArtifactLinker(workflows_root)
        self._workspace_index: Optional[WorkspaceIndex] = None

    @property
    def workspace_index(self) -> WorkspaceIndex:
        """Get or create workspace index (lazy initialization)."""
        if self._workspace_index is None:
            self._workspace_index = WorkspaceIndex(self.workflows_root)
            self._workspace_index.scan_workspace()
        return self._workspace_index

    def resolve_upstream_workflows(
        self,
        agent_configs: dict,
        user_code_path: Optional[str],
        default_path: Optional[str],
        use_tools: bool
    ) -> bool:
        """
        Recursively resolve and execute upstream dependencies.

        Args:
            agent_configs: Dictionary of agent configurations.
            user_code_path: Path to user code directory.
            default_path: Path to default configuration.
            use_tools: Whether to enable tool usage.

        Returns:
            True if all upstreams resolved successfully,
            False if any upstream has pending batch jobs.
        """
        logger.info(
            "Checking upstream dependencies for %s...",
            self.current_workflow,
            extra={'operation': 'resolve_upstream'}
        )
        processed_upstreams = set()

        for config in agent_configs.values():
            for dep in config.get('dependencies', []):
                if isinstance(dep, dict) and 'workflow' in dep:
                    upstream_name = dep['workflow']
                    if upstream_name in processed_upstreams:
                        continue

                    result = self._execute_upstream_workflow(
                        upstream_name, user_code_path, default_path, use_tools
                    )
                    if result is None:
                        # Upstream has pending batch jobs, exit gracefully
                        return False
                    processed_upstreams.add(upstream_name)

        return True

    def _execute_upstream_workflow(
        self,
        upstream_name: str,
        user_code_path: Optional[str],
        default_path: Optional[str],
        use_tools: bool
    ) -> Optional[bool]:
        """
        Execute a single upstream workflow and link artifacts.

        Args:
            upstream_name: Name of the upstream workflow.
            user_code_path: Path to user code directory.
            default_path: Path to default configuration.
            use_tools: Whether to enable tool usage.

        Returns:
            True if upstream is ready, None if batch jobs pending.

        Raises:
            RuntimeError: If upstream execution fails.
        """
        self.console.print(
            f"[bold cyan]>> Recursive: Checking upstream workflow "
            f"'{upstream_name}'...[/bold cyan]"
        )

        try:
            upstream_config_path = (
                self.workflows_root / upstream_name / 'agent_config' /
                f'{upstream_name}.yml'
            )

            if not upstream_config_path.exists():
                raise FileNotFoundError(
                    f"Could not locate upstream config at {upstream_config_path}"
                )

            # Check if upstream workflow is already complete
            all_completed = self._check_workflow_complete(upstream_name)

            if all_completed:
                self.console.print(
                    f"[bold green]>> Upstream workflow "
                    f"'{upstream_name}' already completed, "
                    "using existing data[/bold green]"
                )
            else:
                # Run upstream workflow
                self.console.print(
                    f"[bold cyan]>> Recursive: Executing upstream "
                    f"workflow '{upstream_name}'...[/bold cyan]"
                )
                upstream_wf = self.workflow_factory(
                    config_path=str(upstream_config_path),
                    user_code_path=user_code_path,
                    default_path=default_path,
                    use_tools=use_tools,
                    run_upstream=False,  # Don't trigger recursive check
                    run_downstream=False
                )
                result = upstream_wf.run()

                if result is None:
                    self._print_batch_pending_message(upstream_name, is_upstream=True)
                    return None

            # Link artifacts
            self.artifact_linker.link_upstream_artifacts(upstream_name, self.current_workflow)

            self.console.print(
                f"[bold green]>> Recursive: Ready to use upstream "
                f"data from '{upstream_name}'[/bold green]"
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to execute upstream workflow %s: %s",
                upstream_name, e
            )
            raise RuntimeError(f"Recursive execution failed for {upstream_name}") from e

    def _check_workflow_complete(self, workflow_name: str) -> bool:
        """Check if a workflow is already complete by reading its status file."""
        upstream_status_file = (
            self.workflows_root / workflow_name / 'agent_io' / '.agent_status.json'
        )

        if not upstream_status_file.exists():
            return False

        try:
            with open(upstream_status_file, 'r', encoding='utf-8') as f:
                status_data = json.load(f)
            return all(
                details.get('status') == 'completed'
                for details in status_data.values()
            )
        except (OSError, IOError, json.JSONDecodeError, KeyError):
            return False

    def resolve_downstream_workflows(
        self,
        user_code_path: Optional[str],
        default_path: Optional[str],
        use_tools: bool
    ) -> bool:
        """
        Execute all downstream workflows after current workflow completes.

        Args:
            user_code_path: Path to user code directory.
            default_path: Path to default configuration.
            use_tools: Whether to enable tool usage.

        Returns:
            True if all downstream workflows completed successfully,
            False if any downstream has pending batch jobs.
        """
        logger.info(
            "Checking downstream workflows for %s...",
            self.current_workflow,
            extra={'operation': 'resolve_downstream'}
        )

        # Get sorted downstream workflows
        try:
            downstream_order = self.workspace_index.topological_sort_downstream(
                self.current_workflow
            )
        except Exception as e:
            logger.error("Failed to compute downstream order: %s", e)
            raise

        if not downstream_order:
            self.console.print(
                f"[dim]No downstream workflows found for {self.current_workflow}[/dim]"
            )
            return True

        self.console.print(
            f"\n[bold cyan]>> Found {len(downstream_order)} downstream workflow(s): "
            f"{downstream_order}[/bold cyan]"
        )

        # Execute each downstream workflow in order
        for downstream_name in downstream_order:
            result = self._execute_downstream_workflow(
                downstream_name, user_code_path, default_path, use_tools
            )
            if result is None:
                return False

        return True

    def _execute_downstream_workflow(
        self,
        downstream_name: str,
        user_code_path: Optional[str],
        default_path: Optional[str],
        use_tools: bool
    ) -> Optional[bool]:
        """
        Execute a single downstream workflow.

        Args:
            downstream_name: Name of the downstream workflow.
            user_code_path: Path to user code directory.
            default_path: Path to default configuration.
            use_tools: Whether to enable tool usage.

        Returns:
            True on success, None if batch pending.
        """
        self.console.print(
            f"\n[bold cyan]>> Downstream: Executing workflow '{downstream_name}'...[/bold cyan]"
        )

        downstream_config_path = (
            self.workflows_root / downstream_name /
            'agent_config' / f'{downstream_name}.yml'
        )

        if not downstream_config_path.exists():
            raise FileNotFoundError(
                f"Downstream workflow config not found at {downstream_config_path}"
            )

        # Link current workflow's output to downstream's staging
        self.artifact_linker.link_downstream_artifacts(self.current_workflow, downstream_name)

        # Create and run downstream workflow
        downstream_wf = self.workflow_factory(
            config_path=str(downstream_config_path),
            user_code_path=user_code_path,
            default_path=default_path,
            use_tools=use_tools,
            run_upstream=False,
            run_downstream=False
        )

        result = downstream_wf.run()

        if result is None:
            self._print_batch_pending_message(downstream_name, is_upstream=False)
            return None

        self.console.print(
            f"[bold green]>> Downstream: Workflow '{downstream_name}' completed[/bold green]"
        )
        return True

    def _print_batch_pending_message(self, workflow_name: str, is_upstream: bool) -> None:
        """Print message about pending batch jobs."""
        direction = "Upstream" if is_upstream else "Downstream"
        flag = "--upstream" if is_upstream else "--downstream"

        self.console.print(
            f"[blue]⏳ {direction} workflow '{workflow_name}' "
            "has pending batch jobs.[/blue]"
        )
        self.console.print(
            "[blue]Please wait for batch completion and run this command again:[/blue]"
        )
        self.console.print(
            f"[blue]  agac run -a {self.current_workflow} {flag}[/blue]"
        )

    def resolve_upstream_and_initialize(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        run_upstream: bool,
        agent_configs: dict,
        user_code_path: Optional[str],
        default_path: Optional[str],
        use_tools: bool
    ) -> Optional[bool]:
        """
        Initialize correlation context and resolve upstream dependencies.

        Args:
            run_upstream: Whether to run upstream workflows.
            agent_configs: Dictionary of agent configurations.
            user_code_path: Path to user code directory.
            default_path: Path to default configuration.
            use_tools: Whether to enable tool usage.

        Returns:
            True if should continue, False if upstream has pending batches.
        """
        if not run_upstream:
            return True

        previous_context = CorrelationContext.get_context()
        try:
            CorrelationContext.start_workflow(self.current_workflow)
            should_continue = self.resolve_upstream_workflows(
                agent_configs, user_code_path, default_path, use_tools
            )
            if not should_continue:
                if previous_context:
                    CorrelationContext.set_context(previous_context)
                else:
                    CorrelationContext.clear_context()
                return False
            return True
        except Exception:
            if previous_context:
                CorrelationContext.set_context(previous_context)
            else:
                CorrelationContext.clear_context()
            raise


__all__ = ['WorkflowDependencyOrchestrator']
