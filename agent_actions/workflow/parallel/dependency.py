"""
Workflow dependency orchestration for upstream/downstream execution.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.workflow.managers.artifacts import ArtifactLinker
from agent_actions.workflow.workspace_index import WorkspaceIndex

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


class WorkflowDependencyOrchestrator:
    """Orchestrates upstream and downstream workflow dependencies."""

    def __init__(
        self,
        workflows_root: Path,
        current_workflow: str,
        console: Console,
        workflow_factory: Callable[..., Any],
    ):
        """Initialize the dependency orchestrator."""
        self.workflows_root = workflows_root
        self.current_workflow = current_workflow
        self.console = console
        self.workflow_factory = workflow_factory
        self.artifact_linker = ArtifactLinker(workflows_root)
        self._workspace_index: WorkspaceIndex | None = None

    @property
    def workspace_index(self) -> WorkspaceIndex:
        """Return workspace index, creating it on first access."""
        if self._workspace_index is None:
            self._workspace_index = WorkspaceIndex(self.workflows_root)
            self._workspace_index.scan_workspace()
        return self._workspace_index

    def resolve_upstream_workflows(
        self,
        agent_configs: dict,
        user_code_path: str | None,
        default_path: str | None,
        use_tools: bool,
    ) -> bool:
        """Recursively resolve and execute upstream dependencies.

        Returns:
            False if any upstream has pending batch jobs.
        """
        logger.info(
            "Checking upstream dependencies for %s...",
            self.current_workflow,
            extra={"operation": "resolve_upstream"},
        )
        processed_upstreams = set()

        for config in agent_configs.values():
            for dep in config.get("dependencies", []):
                if isinstance(dep, dict) and "workflow" in dep:
                    upstream_name = dep["workflow"]
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
        user_code_path: str | None,
        default_path: str | None,
        use_tools: bool,
    ) -> bool | None:
        """Execute a single upstream workflow and link artifacts.

        Returns:
            True if upstream is ready, None if batch jobs pending.

        Raises:
            RuntimeError: If upstream execution fails.
        """
        self.console.print(
            f"[bold cyan]>> Recursive: Checking upstream workflow '{upstream_name}'...[/bold cyan]"
        )

        try:
            upstream_config_path = (
                self.workflows_root / upstream_name / "agent_config" / f"{upstream_name}.yml"
            )

            if not upstream_config_path.exists():
                raise FileNotFoundError(
                    f"Could not locate upstream config at {upstream_config_path}"
                )

            all_completed = self._check_workflow_complete(upstream_name)

            if all_completed:
                self.console.print(
                    f"[bold green]>> Upstream workflow "
                    f"'{upstream_name}' already completed, "
                    "using existing data[/bold green]"
                )
            else:
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
                    run_downstream=False,
                )
                result = upstream_wf.run()

                if result is None:
                    self._print_batch_pending_message(upstream_name, is_upstream=True)
                    return None

            self.artifact_linker.link_upstream_artifacts(upstream_name, self.current_workflow)

            self.console.print(
                f"[bold green]>> Recursive: Ready to use upstream "
                f"data from '{upstream_name}'[/bold green]"
            )
            return True

        except Exception as e:
            logger.debug("Failed to execute upstream workflow %s: %s", upstream_name, e)
            raise RuntimeError(
                f"Recursive execution failed for upstream workflow '{upstream_name}': "
                f"{type(e).__name__}: {e}"
            ) from e

    def _check_workflow_complete(self, workflow_name: str) -> bool:
        """Check if a workflow is already complete by reading its status file."""
        upstream_status_file = (
            self.workflows_root / workflow_name / "agent_io" / ".agent_status.json"
        )

        if not upstream_status_file.exists():
            return False

        try:
            with open(upstream_status_file, encoding="utf-8") as f:
                status_data = json.load(f)
            return all(details.get("status") == "completed" for details in status_data.values())
        except (OSError, json.JSONDecodeError, KeyError):
            return False

    def resolve_downstream_workflows(
        self, user_code_path: str | None, default_path: str | None, use_tools: bool
    ) -> bool:
        """Execute all downstream workflows after current workflow completes.

        Returns:
            False if any downstream has pending batch jobs.
        """
        logger.info(
            "Checking downstream workflows for %s...",
            self.current_workflow,
            extra={"operation": "resolve_downstream"},
        )

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
        user_code_path: str | None,
        default_path: str | None,
        use_tools: bool,
    ) -> bool | None:
        """Execute a single downstream workflow. Return None if batch pending."""
        self.console.print(
            f"\n[bold cyan]>> Downstream: Executing workflow '{downstream_name}'...[/bold cyan]"
        )

        downstream_config_path = (
            self.workflows_root / downstream_name / "agent_config" / f"{downstream_name}.yml"
        )

        if not downstream_config_path.exists():
            raise FileNotFoundError(
                f"Downstream workflow config not found at {downstream_config_path}"
            )

        self.artifact_linker.link_downstream_artifacts(self.current_workflow, downstream_name)

        downstream_wf = self.workflow_factory(
            config_path=str(downstream_config_path),
            user_code_path=user_code_path,
            default_path=default_path,
            use_tools=use_tools,
            run_upstream=False,
            run_downstream=False,
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
            f"[blue]⏳ {direction} workflow '{workflow_name}' has pending batch jobs.[/blue]"
        )
        self.console.print(
            "[blue]Please wait for batch completion and run this command again:[/blue]"
        )
        self.console.print(f"[blue]  agac run -a {self.current_workflow} {flag}[/blue]")


__all__ = ["WorkflowDependencyOrchestrator"]
