"""Agent workflow orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from uuid import uuid4

from rich.console import Console

from agent_actions.config.defaults import StorageDefaults
from agent_actions.errors import ConfigurationError, enrich_exception_context
from agent_actions.logging.core.manager import get_manager
from agent_actions.storage.backend import RUNNING_CLEAR_DISPOSITIONS
from agent_actions.validation.preflight.guard_validation import validate_guard_conditions
from agent_actions.workflow.config_pipeline import load_workflow_configs
from agent_actions.workflow.context_scope_pruning import strip_unreachable_drops
from agent_actions.workflow.execution_events import WorkflowEventLogger
from agent_actions.workflow.managers.state import ActionStatus
from agent_actions.workflow.models import (
    ActionLogParams,
    RuntimeContext,
    WorkflowRuntimeConfig,
    WorkflowState,
)
from agent_actions.workflow.service_init import initialize_services, initialize_storage_backend

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """Orchestrates multi-agent workflow execution."""

    def __init__(self, config: WorkflowRuntimeConfig):
        """Initialize workflow with configuration and dependencies."""
        self.config = config
        self.runtime = RuntimeContext(state=WorkflowState(), console=Console(stderr=True))

        # Config pipeline (fires WorkflowInitializationStartEvent internally)
        self.metadata = load_workflow_configs(config, self.console)
        self._run_static_validation()
        strip_unreachable_drops(self.action_configs)

        # Storage & services
        self.storage_backend = initialize_storage_backend(config, self.metadata, self.console)
        if self.storage_backend is None:
            raise ConfigurationError(
                "storage_backend could not be initialized — check storage configuration.",
                context={"component": "WorkflowCoordinator", "operation": "initialize_storage"},
            )
        self.services, self._agent_folder = initialize_services(
            self.metadata, config, self.storage_backend, self.console
        )

        # Fresh run: clear stored results + status before anything else
        if config.fresh:
            self._clear_for_fresh_run()
        else:
            self._reset_retryable_actions()

        # Session
        self.workflow_session_id = self._generate_workflow_session_id()
        self._prepare_action_configs()

        # Event logger (after services are ready)
        self.event_logger = WorkflowEventLogger(
            self.agent_name, self.execution_order, self.config, self.services
        )

    # ── Static validation ─────────────────────────────────────────────

    def _run_static_validation(self) -> None:
        """Run static analysis on the workflow config before execution.

        Validates context_scope field references, schema structures, and
        data flow — like dbt compile before dbt run. Raises on errors.
        """
        from agent_actions.services.preflight_service import PreflightService

        service = PreflightService(
            agent_name=self.agent_name,
            action_configs=self.action_configs,
            project_root=self.config.resolve_project_root(),
            workflow_config_path=self.config.paths.constructor_path,
            verify_keys=self.config.verify_keys,
        )
        service.validate()
        # Reuse the rebuilt schema service to avoid a second pass.
        self.schema_service = service.schema_service

    def _validate_guard_conditions(self) -> list[str]:
        return validate_guard_conditions(self.action_configs)

    def _clear_for_fresh_run(self) -> None:
        """Clear stored results, dispositions, status, and event logs for a fresh run."""
        project_root = self.config.resolve_project_root()

        target_dir = project_root / "agent_io" / "target"
        for action_name in self.execution_order:
            for op_name, op_call in [
                ("target", lambda a=action_name: self.storage_backend.delete_target(a)),
                ("dispositions", lambda a=action_name: self.storage_backend.clear_disposition(a)),
                (
                    "prompt_traces",
                    lambda a=action_name: self.storage_backend.clear_prompt_traces(a),
                ),
                (
                    "checkpoints",
                    lambda a=action_name: self.storage_backend.clear_checkpoint_records(a),
                ),
                ("batch_state", lambda a=action_name: self.storage_backend.clear_batch_state(a)),
            ]:
                try:
                    op_call()
                except Exception as e:
                    logger.warning("Failed to clear %s for %s: %s", op_name, action_name, e)

            batch_dir = target_dir / action_name / "batch"
            if batch_dir.is_dir():
                for f in batch_dir.iterdir():
                    if f.suffix in (".jsonl", ".json"):
                        try:
                            f.unlink(missing_ok=True)
                        except OSError:
                            logger.debug("Could not delete batch artifact: %s", f)

        try:
            self.storage_backend.clear_source_data()
        except Exception as e:
            logger.warning("Failed to clear source data: %s", e)

        self.services.core.state_manager.reset()

        # JSONFileHandler opens lazily, so deleting between handler init
        # and first event write is safe.
        logs_dir = project_root / "agent_io" / "logs"
        for events_file in ("events.json", "errors.json"):
            for search_dir in (logs_dir, target_dir):
                try:
                    (search_dir / events_file).unlink(missing_ok=True)
                except OSError as e:
                    logger.warning("Failed to clear %s: %s", events_file, e)

        self.console.print(
            "[yellow]--fresh: cleared stored results and reset all actions to pending[/yellow]"
        )

    def _reset_retryable_actions(self) -> None:
        """Reset failed/skipped/running actions to pending so re-runs retry them.

        For most statuses, clears ALL dispositions — disposition is derived
        state that must follow action status.  For RUNNING actions (interrupted
        mid-processing), only failure dispositions are cleared so that
        checkpointed SUCCESS rows survive and the DispositionGate can carry
        them forward on resume.
        """
        state_mgr = self.services.core.state_manager
        # Snapshot RUNNING actions before reset_retryable() transitions them
        # to PENDING — must be captured first so we know which actions had
        # checkpointed progress to preserve.
        running_actions = {
            name
            for name in state_mgr.execution_order
            if state_mgr.get_status(name) == ActionStatus.RUNNING
        }
        reset_actions = state_mgr.reset_retryable()
        if not reset_actions:
            return
        for action_name in reset_actions:
            try:
                if action_name in running_actions:
                    for disp in RUNNING_CLEAR_DISPOSITIONS:
                        self.storage_backend.clear_disposition(action_name, disp)
                else:
                    self.storage_backend.clear_disposition(action_name)
            except Exception as e:
                logger.warning("Failed to clear dispositions for %s: %s", action_name, e)
            try:
                self.storage_backend.clear_prompt_traces(action_name)
            except Exception as e:
                logger.warning("Failed to clear prompt traces for %s: %s", action_name, e)
        logger.info("Reset %d action(s) for retry: %s", len(reset_actions), reset_actions)

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def state(self):
        """Return workflow state from runtime context."""
        return self.runtime.state

    @property
    def console(self):
        """Return console from runtime context."""
        return self.runtime.console

    @property
    def agent_name(self) -> str:
        """Return agent name from metadata."""
        return self.metadata.agent_name

    @property
    def execution_order(self) -> list:
        """Return execution order from metadata."""
        return self.metadata.execution_order

    @property
    def action_indices(self) -> dict:
        """Return action indices from metadata."""
        return self.metadata.action_indices

    @property
    def action_configs(self) -> dict:
        """Return action configs from metadata."""
        return self.metadata.action_configs

    # ── Session management ──────────────────────────────────────────────

    def _generate_workflow_session_id(self) -> str:
        """Generate a deterministic workflow session ID from config path + agent name."""
        config_content = f"{self.config.paths.constructor_path}:{self.agent_name}"
        config_hash = hashlib.sha256(config_content.encode()).hexdigest()[:16]
        return f"workflow_{config_hash}"

    def _prepare_action_configs(self):
        """Inject workflow-level metadata into all action configurations.

        Sets action_name and workflow_session_id on each config so both
        online and batch paths resolve identity from the same source.
        """
        from agent_actions.utils.correlation import VersionIdGenerator

        VersionIdGenerator.clear_version_correlation_registry()

        for action_name, action_config in self.action_configs.items():
            action_config["action_name"] = action_name
            action_config["workflow_session_id"] = self.workflow_session_id

    def _initialize_event_context(self) -> None:
        """Initialize event context for workflow execution."""
        get_manager().set_context(workflow_name=self.agent_name, correlation_id=str(uuid4())[:8])

    # ── Execution ───────────────────────────────────────────────────────

    def _persist_execution_metadata(self, levels: list[list[str]]) -> None:
        """Store execution order and dependency graph in workflow metadata."""
        backend = getattr(self, "storage_backend", None)
        if backend is None:
            return
        backend.save_metadata("execution_order", json.dumps(self.execution_order))
        prior_actions: list[str] = []
        dep_graph: dict[str, list[str]] = {}
        for level_actions in levels:
            for action in level_actions:
                dep_graph[action] = list(prior_actions)
            prior_actions.extend(level_actions)
        backend.save_metadata("dependency_graph", json.dumps(dep_graph))

    async def async_run(self, concurrency_limit: int = 5):
        """Execute workflow level-by-level with parallelism within each level."""
        self._initialize_event_context()

        workflow_start = datetime.now()
        self.event_logger.log_workflow_start(workflow_start, is_async=True)

        manager = get_manager()
        with manager.context():
            try:
                levels = self.services.core.action_level_orchestrator.compute_execution_levels()
                self._persist_execution_metadata(levels)
                self.services.core.action_level_orchestrator.log_execution_levels(
                    levels, self.action_indices
                )

                from agent_actions.workflow.parallel.action_executor import LevelExecutionParams

                for level_idx, level_actions in enumerate(levels):
                    for action_name in level_actions:
                        if action_name in self.action_indices:
                            manager.set_context(
                                action_name=action_name,
                                action_index=self.action_indices[action_name],
                            )

                    orchestrator = self.services.core.action_level_orchestrator
                    level_complete = await orchestrator.execute_level_async(
                        LevelExecutionParams(
                            level_idx=level_idx,
                            level_actions=level_actions,
                            action_indices=self.action_indices,
                            state_manager=self.services.core.state_manager,
                            action_executor=self.services.core.action_executor,
                            concurrency_limit=concurrency_limit,
                        )
                    )

                    if not level_complete:
                        return

                state_mgr = self.services.core.state_manager
                duration = (datetime.now() - workflow_start).total_seconds()

                if state_mgr.is_workflow_complete():
                    self.event_logger.finalize_workflow(elapsed_time=duration)
                    self._run_storage_maintenance()
                    return ("success", {})

                if state_mgr.is_workflow_done():
                    self.state.failed = True
                    self.event_logger.finalize_workflow(elapsed_time=duration)
                    self._run_storage_maintenance()
                    failed = state_mgr.get_failed_actions(self.execution_order)
                    return ("completed_with_failures", {"failed": failed})

                return None

            except Exception as e:
                duration = (datetime.now() - workflow_start).total_seconds()
                self.state.failed = True
                # Enrich BEFORE firing the error event so the formatter
                # has full context when it renders the user-facing message.
                enrich_exception_context(
                    e,
                    workflow=self.metadata.agent_name,
                    operation="async_workflow_execution",
                )
                self.event_logger.handle_workflow_error(e, elapsed_time=duration)
                raise

    def run(self):
        """Execute workflow sequentially."""
        self._initialize_event_context()

        workflow_start = datetime.now()
        self.event_logger.log_workflow_start(workflow_start, is_async=False)

        return self._run_workflow_with_context(workflow_start)

    def _run_workflow_with_context(self, workflow_start):
        """Execute workflow with retry tracking context active."""
        manager = get_manager()
        with manager.context():
            try:
                total_actions = len(self.execution_order)
                levels = self.services.core.action_level_orchestrator.compute_execution_levels()
                self._persist_execution_metadata(levels)
                self.services.core.action_level_orchestrator.log_execution_levels(
                    levels, self.action_indices
                )
                self.console.print(f"Found {total_actions} actions to run.")
                state_mgr = self.services.core.state_manager
                executor = self.services.core.action_executor

                for level_idx, level_actions in enumerate(levels):
                    # Verify completed actions still have outputs (matches
                    # parallel executor — resets stale completions to pending)
                    for action_name in level_actions:
                        if state_mgr.is_completed(action_name):
                            executor.verify_completion_status(action_name)

                    pending = [a for a in level_actions if not state_mgr.is_completed(a)]
                    if not pending:
                        self.console.print(
                            f"[yellow]Step {level_idx}: All actions complete (skipped)[/yellow]"
                        )
                        continue

                    action_count = len(pending)
                    self.console.print(
                        f"[cyan]Step {level_idx}: Starting "
                        f"{action_count} {'action' if action_count == 1 else 'actions'}...[/cyan]"
                    )

                    level_start = datetime.now()
                    stop = False
                    for action_name in pending:
                        idx = self.action_indices[action_name]
                        manager.set_context(action_name=action_name, action_index=idx)
                        should_stop = self._run_single_action(idx, action_name, total_actions)
                        if should_stop:
                            stop = True
                            break

                    level_duration = (datetime.now() - level_start).total_seconds()
                    has_failed = any(state_mgr.is_failed(a) for a in level_actions)
                    color = "red" if has_failed else "green"
                    self.console.print(
                        f"[{color}]Step {level_idx} complete ({level_duration:.2f}s)[/{color}]"
                    )

                    if stop:
                        break

                state_mgr = self.services.core.state_manager
                duration = (datetime.now() - workflow_start).total_seconds()

                if state_mgr.is_workflow_complete():
                    self.event_logger.finalize_workflow(elapsed_time=duration)
                    self._run_storage_maintenance()
                    return ("success", {})

                if state_mgr.is_workflow_done():
                    # All actions reached a terminal state but some failed
                    self.state.failed = True
                    self.event_logger.finalize_workflow(elapsed_time=duration)
                    self._run_storage_maintenance()
                    failed = state_mgr.get_failed_actions(self.execution_order)
                    return ("completed_with_failures", {"failed": failed})

                return None

            except Exception as e:
                duration = (datetime.now() - workflow_start).total_seconds()
                self.state.failed = True
                # Enrich BEFORE firing the error event so the formatter
                # has full context when it renders the user-facing message.
                enrich_exception_context(
                    e,
                    workflow=self.metadata.agent_name,
                    operation="sequential_workflow_execution",
                )
                self.event_logger.handle_workflow_error(e, elapsed_time=duration)
                raise

    def _run_storage_maintenance(self) -> None:
        """Run post-workflow storage maintenance (WAL checkpoint, cleanup)."""
        backend = getattr(self, "storage_backend", None)
        if backend is None:
            return

        storage_config: dict = {}
        config_mgr = getattr(self.config, "manager", None)
        if config_mgr is not None:
            user_cfg = getattr(config_mgr, "user_config", None)
            if isinstance(user_cfg, dict):
                storage_config = user_cfg.get("storage", {})

        backend.perform_maintenance(
            prompt_trace_retention_runs=storage_config.get(
                "prompt_trace_retention_runs",
                StorageDefaults.PROMPT_TRACE_RETENTION_RUNS,
            ),
            source_data_ttl_days=storage_config.get(
                "source_data_ttl_days",
                StorageDefaults.SOURCE_DATA_TTL_DAYS,
            ),
        )

    def _run_single_action(self, idx: int, action_name: str, total_actions: int) -> bool:
        """Run a single action in sequential mode. Return True if workflow should stop."""
        action_config = self.action_configs[action_name]
        start_time = datetime.now()

        self.event_logger.fire_action_start(idx, action_name, total_actions, action_config)

        run_mode = action_config.get("run_mode", "")

        if self.services.core.state_manager.is_completed(action_name):
            if self.services.core.action_executor.verify_completion_status(action_name):
                self.event_logger.log_action_skip(idx, action_name, total_actions, run_mode)
                return False
            # verify_completion_status reset the action to "pending" — fall through to re-run

        is_last = idx == len(self.execution_order) - 1
        result = self.services.core.action_executor.execute_action_sync(
            action_name, action_idx=idx, action_config=action_config, is_last_action=is_last
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        self.event_logger.log_action_result(
            ActionLogParams(
                idx=idx,
                action_name=action_name,
                total_actions=total_actions,
                result=result,
                end_time=end_time,
                duration=duration,
                run_mode=run_mode,
            )
        )

        if result.success:
            if result.status == ActionStatus.BATCH_SUBMITTED:
                return True

            if result.status == ActionStatus.SKIPPED:
                return False  # Continue to next action

            return False

        # Action failed — log and continue (circuit breaker handles downstream)
        logger.warning("Action '%s' failed: %s", action_name, result.error)
        return False
