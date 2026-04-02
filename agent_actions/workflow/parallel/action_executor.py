"""
Action-level execution orchestration module.
"""

import asyncio
import copy
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.console import Console

from agent_actions.errors import WorkflowError, get_error_detail
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import ActionCompleteEvent, ActionFailedEvent
from agent_actions.workflow.managers.state import COMPLETED_STATUSES

logger = logging.getLogger(__name__)


@dataclass
class ParallelExecutionParams:
    """Parameters for executing parallel actions."""

    pending_actions: list[str]
    action_indices: dict
    action_executor: Any
    concurrency_limit: int
    level_idx: int


@dataclass
class LevelExecutionParams:
    """Parameters for executing a level."""

    level_idx: int
    level_actions: list[str]
    action_indices: dict[str, int]
    state_manager: Any
    action_executor: Any
    concurrency_limit: int = 5


class ActionLevelOrchestrator:
    """Orchestrates action execution by dependency levels."""

    def __init__(
        self,
        execution_order: list[str],
        action_configs: dict[str, dict[str, Any]],
        console: Console | None = None,
    ):
        """Initialize level orchestrator."""
        self.execution_order = execution_order
        self.action_configs = action_configs
        self.console = console or Console()

    def _build_version_base_name_map(self) -> dict[str, list[str]]:
        """Build a mapping from version base names to their expanded action names."""
        version_base_map: dict[str, list[str]] = {}
        for action_name in self.execution_order:
            config = self.action_configs[action_name]
            if config.get("is_versioned_agent"):
                base_name = config.get("version_base_name")
                if base_name:
                    if base_name not in version_base_map:
                        version_base_map[base_name] = []
                    version_base_map[base_name].append(action_name)
        return version_base_map

    def _expand_version_dependencies(
        self, dependencies: list[str], version_base_map: dict[str, list[str]]
    ) -> list[str]:
        """Expand dependencies that reference version base names to their expanded variants."""
        expanded = []
        for dep in dependencies:
            if dep in version_base_map:
                # Dependency references a version base name - expand to all variants
                expanded.extend(version_base_map[dep])
            else:
                # Regular dependency - keep as-is
                expanded.append(dep)
        return expanded

    def compute_execution_levels(self) -> list[list[str]]:
        """Compute execution levels from dependency graph.

        Raises:
            WorkflowError: If circular dependencies are detected.
        """
        # Build mapping of version base names to their expanded variants
        version_base_map = self._build_version_base_name_map()

        local_configs = copy.deepcopy(self.action_configs)
        deps_map = {}
        for action in self.execution_order:
            raw_deps = [
                d for d in local_configs[action].get("dependencies", []) if isinstance(d, str)
            ]
            # Expand any version base name references to their expanded variants
            expanded_deps = self._expand_version_dependencies(raw_deps, version_base_map)
            deps_map[action] = expanded_deps
            if expanded_deps != raw_deps:
                local_configs[action]["dependencies"] = expanded_deps

        levels = []
        assigned: set[str] = set()

        while len(assigned) < len(self.execution_order):
            # Find actions whose dependencies are all satisfied
            current_level = [
                action
                for action in self.execution_order
                if action not in assigned and all(dep in assigned for dep in deps_map[action])
            ]

            if not current_level:
                remaining_actions = set(self.execution_order) - assigned
                unsatisfied_deps = {
                    action: [dep for dep in deps_map[action] if dep not in assigned]
                    for action in remaining_actions
                }

                error_details = "\n".join(
                    [
                        f"  - {action} waiting for: {', '.join(deps)}"
                        for action, deps in unsatisfied_deps.items()
                    ]
                )

                raise WorkflowError(
                    f"Circular dependency detected - cannot compute execution levels.\n\n"
                    f"Actions blocked:\n{error_details}",
                    {
                        "error_type": "circular_dependency",
                        "assigned": list(assigned),
                        "remaining": list(remaining_actions),
                        "unsatisfied_dependencies": unsatisfied_deps,
                    },
                )

            levels.append(current_level)
            assigned.update(current_level)

        return levels

    def should_use_parallel_execution(self) -> bool:
        """Return True if any execution level has more than 1 action."""
        levels = self.compute_execution_levels()
        return any(len(level) > 1 for level in levels)

    def log_execution_levels(self, levels: list[list[str]], action_indices: dict[str, int]):
        """Log execution levels for user transparency."""
        total_actions = sum(len(level) for level in levels)
        self.console.print(
            f"[blue]📊 Execution: {total_actions} action(s) in {len(levels)} step(s)[/blue]"
        )

        for i, level in enumerate(levels):
            if len(level) > 1:
                sorted_actions = sorted(level, key=lambda a: action_indices[a])
                action_list = ", ".join(sorted_actions)
                self.console.print(
                    f"[blue]  Step {i}: {len(level)} actions in parallel - {action_list}[/blue]"
                )
            else:
                self.console.print(f"[dim]  Step {i}: {level[0]} (sequential)[/dim]")

    async def _execute_single_action(self, action_name: str, action_indices: dict, action_executor):
        """Execute a single action asynchronously."""
        original_idx = action_indices[action_name]
        action_config = self.action_configs[action_name]
        is_last = original_idx == len(self.execution_order) - 1
        total_actions = len(self.execution_order)

        result = await action_executor.execute_action_async(
            action_name,
            action_idx=original_idx,
            action_config=action_config,
            is_last_action=is_last,
        )

        self._fire_action_result_event(action_name, original_idx, total_actions, result)

        if not result.success:
            logger.warning("Action '%s' failed: %s", action_name, result.error)

    async def _execute_parallel_actions(self, params: ParallelExecutionParams):
        """Execute multiple actions in parallel."""
        self.console.print(f"[blue]  → {len(params.pending_actions)} actions in parallel[/blue]")
        semaphore = asyncio.Semaphore(params.concurrency_limit)

        total_actions = len(self.execution_order)

        async def run_with_limit(action):
            """Run action with semaphore limit, firing events on completion."""
            async with semaphore:
                original_idx = params.action_indices[action]
                action_config = self.action_configs[action]
                is_last = original_idx == len(self.execution_order) - 1

                try:
                    result = await params.action_executor.execute_action_async(
                        action,
                        action_idx=original_idx,
                        action_config=action_config,
                        is_last_action=is_last,
                    )
                except Exception as exc:
                    fire_event(
                        ActionFailedEvent(
                            action_name=action,
                            action_index=original_idx,
                            total_actions=total_actions,
                            error_message=str(exc),
                            error_detail=get_error_detail(exc),
                            error_type=type(exc).__name__,
                        )
                    )
                    raise

                self._fire_action_result_event(action, original_idx, total_actions, result)
                return result

        tasks = [run_with_limit(action) for action in params.pending_actions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors = []
        for action, result in zip(params.pending_actions, results, strict=True):
            if isinstance(result, BaseException):
                errors.append((action, result))
            elif not result.success:
                errors.append((action, result.error))

        if errors:
            error_details = "\n".join([f"  - {action}: {str(exc)}" for action, exc in errors])
            logger.warning(
                "Level %d: %d action(s) failed:\n%s",
                params.level_idx,
                len(errors),
                error_details,
            )

    def _fire_action_result_event(self, action_name: str, idx: int, total: int, result):
        """Fire action complete or failed event for an execution result."""
        if result.success and result.status in COMPLETED_STATUSES:
            tokens = result.metrics.tokens if result.metrics and result.metrics.tokens else {}
            fire_event(
                ActionCompleteEvent(
                    action_name=action_name,
                    action_index=idx,
                    total_actions=total,
                    execution_time=result.metrics.duration if result.metrics else 0.0,
                    output_path=result.output_folder or "",
                    tokens=tokens,
                )
            )
        elif not result.success:
            fire_event(
                ActionFailedEvent(
                    action_name=action_name,
                    action_index=idx,
                    total_actions=total,
                    error_message=str(result.error) if result.error else "",
                    error_detail=get_error_detail(result.error) if result.error else "",
                    error_type=type(result.error).__name__ if result.error else "",
                    execution_time=result.metrics.duration if result.metrics else 0.0,
                )
            )
        # batch_submitted: BatchSubmittedEvent already fired by executor

    def _check_batch_status(
        self, level_idx: int, level_actions: list[str], state_manager, start_time: datetime
    ) -> bool:
        """Check batch submission status and handle accordingly."""
        batch_pending = state_manager.get_batch_submitted_actions(level_actions)

        if batch_pending:
            # Log partial failures but don't raise — circuit breaker handles cascade
            failed_actions = state_manager.get_failed_actions(level_actions)
            if failed_actions:
                logger.warning(
                    "Level %d: %s failed while batch jobs pending for %s",
                    level_idx,
                    ", ".join(failed_actions),
                    ", ".join(batch_pending),
                )

            # Batch jobs submitted, need to wait
            duration = (datetime.now() - start_time).total_seconds()
            self.console.print(
                f"[yellow]Step {level_idx}: {len(batch_pending)} "
                f"batch job(s) submitted ({duration:.2f}s)[/yellow]"
            )
            self.console.print("[yellow]Run workflow again to check batch status[/yellow]")
            return False  # Level not complete

        return True  # No batch pending

    async def execute_level_async(self, params: LevelExecutionParams) -> bool:
        """Execute all actions in a level asynchronously.

        Returns:
            True if level completed, False if batch jobs pending.

        Failed actions are logged but do not raise — the circuit breaker
        in ActionExecutor handles downstream skipping.
        """
        start_time = datetime.now()

        # Verify that every "completed" action in this level still has its output
        # in the storage backend.  If the DB was cleared or the backend was swapped
        # since the last run, _verify_completion_status resets the action to
        # "pending" so it re-runs before its downstream dependents need the data.
        # Without this, the completed-action early-return in execute_action_async
        # is unreachable (get_pending_actions filters them out first), making the
        # verification logic dead code and causing downstream "not found" failures.
        for action_name in params.level_actions:
            if params.state_manager.is_completed(action_name):
                params.action_executor.verify_completion_status(action_name)

        # Filter to pending actions only (verification above may have reset some)
        pending_actions = params.state_manager.get_pending_actions(params.level_actions)

        if not pending_actions:
            self.console.print(
                f"[yellow]Step {params.level_idx}: All actions complete (skipped)[/yellow]"
            )
            return True

        self.console.print(
            f"[cyan]Step {params.level_idx}: Starting {len(pending_actions)} action(s)...[/cyan]"
        )

        if len(pending_actions) == 1:
            await self._execute_single_action(
                pending_actions[0], params.action_indices, params.action_executor
            )
        else:
            await self._execute_parallel_actions(
                ParallelExecutionParams(
                    pending_actions=pending_actions,
                    action_indices=params.action_indices,
                    action_executor=params.action_executor,
                    concurrency_limit=params.concurrency_limit,
                    level_idx=params.level_idx,
                )
            )

        if not self._check_batch_status(
            params.level_idx, params.level_actions, params.state_manager, start_time
        ):
            return False

        duration = (datetime.now() - start_time).total_seconds()

        has_failed = params.state_manager.get_failed_actions(params.level_actions)
        has_partial = any(
            params.state_manager.is_completed_with_failures(a) for a in params.level_actions
        )
        has_skipped = any(params.state_manager.is_skipped(a) for a in params.level_actions)
        if has_failed:
            color = "red"
        elif has_partial or has_skipped:
            color = "yellow"
        else:
            color = "green"
        self.console.print(f"[{color}]Step {params.level_idx} complete ({duration:.2f}s)[/{color}]")
        return True
