"""Agent workflow orchestration."""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from rich.console import Console

from agent_actions.errors import ConfigurationError
from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser
from agent_actions.logging import get_manager
from agent_actions.workflow.config_pipeline import load_workflow_configs
from agent_actions.workflow.execution_events import WorkflowEventLogger
from agent_actions.workflow.managers.artifacts import ArtifactLinker
from agent_actions.workflow.models import (
    ActionLogParams,
    RuntimeContext,
    WorkflowPaths,
    WorkflowRuntimeConfig,
    WorkflowState,
)
from agent_actions.workflow.parallel.dependency import WorkflowDependencyOrchestrator
from agent_actions.workflow.schema_service import WorkflowSchemaService
from agent_actions.workflow.service_init import initialize_services, initialize_storage_backend

logger = logging.getLogger(__name__)


def validate_guard_conditions(action_configs: dict) -> list[str]:
    """Parse all guard conditions and return error messages for any that are invalid.

    Runs after config expansion, so guard dicts already use 'clause' (not 'condition').
    Catches syntax errors (e.g. unbalanced parens, unknown operators) before any LLM
    calls are made.

    Args:
        action_configs: Mapping of action name → expanded agent config dict.

    Returns:
        List of human-readable error strings, one per invalid guard clause.
        Empty list means all guards are syntactically valid.
    """
    errors: list[str] = []
    parser = WhereClauseParser()

    for action_name, config in action_configs.items():
        guard = config.get("guard")
        if not guard or not isinstance(guard, dict):
            continue
        clause = guard.get("clause")
        if not clause:
            continue

        parse_result = parser.parse_cached(clause)
        if not parse_result.success:
            error = parse_result.error
            detail = error.message if error else "parse failed"
            errors.append(f"Action '{action_name}': invalid guard condition '{clause}': {detail}")

    return errors


class AgentWorkflow:
    """Orchestrates multi-agent workflow execution."""

    def __init__(self, config: WorkflowRuntimeConfig):
        """Initialize workflow with configuration and dependencies."""
        self.config = config
        self.runtime = RuntimeContext(state=WorkflowState(), console=Console())

        # Config pipeline (fires WorkflowInitializationStartEvent internally)
        self.metadata = load_workflow_configs(config, self.console)
        self._run_static_validation()

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

        # Dependency orchestration + session
        self._init_dependency_orchestrator()
        self.workflow_session_id = self._generate_workflow_session_id()
        self._inject_workflow_session_id()

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
        self.schema_service = WorkflowSchemaService.from_action_configs(
            self.agent_name,
            self.action_configs,
            project_root=self.config.resolve_project_root(),
            with_udf_registry=True,
        )

        result = self.schema_service.validate()
        if result.errors:
            raise PreFlightValidationError(
                result.format_report(),
                hint="Fix the static type errors above before running the workflow.",
            )

        guard_errors = self._validate_guard_conditions()
        if guard_errors:
            raise PreFlightValidationError(
                "\n".join(guard_errors),
                hint="Fix the guard condition syntax errors above before running the workflow.",
            )

    def _validate_guard_conditions(self) -> list[str]:
        return validate_guard_conditions(self.action_configs)

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

    @property
    def child_pipeline(self) -> str | None:
        """Return child pipeline from metadata."""
        return self.metadata.child_pipeline

    # ── Dependency orchestration ────────────────────────────────────────

    def _init_dependency_orchestrator(self) -> None:
        """Initialize the workflow dependency orchestrator."""
        workflows_root = self._get_workflows_root()
        self.dependency_orchestrator = WorkflowDependencyOrchestrator(
            workflows_root=workflows_root,
            current_workflow=self.agent_name,
            console=self.console,
            workflow_factory=self._create_child_workflow,
        )
        self.artifact_linker = ArtifactLinker(workflows_root)

    def _create_child_workflow(
        self,
        config_path: str,
        user_code_path: str | None,
        default_path: str | None,
        use_tools: bool,
        run_upstream: bool,
        run_downstream: bool,
    ) -> "AgentWorkflow":
        """Factory method to create child workflow instances."""
        return self.__class__(
            WorkflowRuntimeConfig(
                paths=WorkflowPaths(
                    constructor_path=config_path,
                    user_code_path=user_code_path,
                    default_path=default_path or "",
                ),
                use_tools=use_tools,
                run_upstream=run_upstream,
                run_downstream=run_downstream,
                project_root=self.config.project_root,
            )
        )

    def _get_workflows_root(self) -> Path:
        """Get the root directory containing all workflows."""
        current_config_path = Path(self.config.paths.constructor_path)
        # Expects: .../workflows/CURRENT/agent_config/current.yml
        # parents[2] navigates to the workflows root.
        if len(current_config_path.parents) < 3:
            raise ValueError(
                f"Config path too shallow to derive workflows root: {current_config_path} "
                f"(expected .../workflows/WORKFLOW/agent_config/file.yml)"
            )
        return current_config_path.parents[2]

    # ── Session management ──────────────────────────────────────────────

    def _generate_workflow_session_id(self) -> str:
        """Generate a deterministic workflow session ID from config path + agent name."""
        config_content = f"{self.config.paths.constructor_path}:{self.agent_name}"
        config_hash = hashlib.sha256(config_content.encode()).hexdigest()[:16]
        return f"workflow_{config_hash}"

    def _inject_workflow_session_id(self):
        """Inject workflow session ID into all action configurations."""
        from agent_actions.utils.correlation import VersionIdGenerator

        VersionIdGenerator.clear_version_correlation_registry()

        for action_config in self.action_configs.values():
            action_config["workflow_session_id"] = self.workflow_session_id

    # ── Upstream / downstream resolution ────────────────────────────────

    def _resolve_upstream_workflows(self) -> bool:
        """Recursively resolve and execute upstream dependencies."""
        if not self.config.run_upstream:
            return True
        return self.dependency_orchestrator.resolve_upstream_workflows(
            agent_configs=self.action_configs,
            user_code_path=self.config.paths.user_code_path,
            default_path=self.config.paths.default_path,
            use_tools=self.config.use_tools,
        )

    def _resolve_downstream_workflows(self) -> bool:
        """Execute all downstream workflows after current workflow completes."""
        if not self.config.run_downstream:
            return True
        return self.dependency_orchestrator.resolve_downstream_workflows(
            user_code_path=self.config.paths.user_code_path,
            default_path=self.config.paths.default_path,
            use_tools=self.config.use_tools,
        )

    def _resolve_upstream_and_initialize(self) -> bool | None:
        """Initialize event context and resolve upstream dependencies.

        Returns:
            True to continue, False if upstream has pending batches.
        """
        get_manager().set_context(workflow_name=self.agent_name, correlation_id=str(uuid4())[:8])

        should_continue = self._resolve_upstream_workflows()
        if not should_continue:
            return False
        return True

    # ── Execution ───────────────────────────────────────────────────────

    async def async_run(self, concurrency_limit: int = 5):
        """Execute workflow level-by-level with parallelism within each level."""
        should_continue = self._resolve_upstream_and_initialize()
        if should_continue is False:
            return None

        workflow_start = datetime.now()
        self.event_logger.log_workflow_start(workflow_start, is_async=True)

        manager = get_manager()
        with manager.context():
            try:
                levels = self.services.core.action_level_orchestrator.compute_execution_levels()
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

                duration = (datetime.now() - workflow_start).total_seconds()
                self.event_logger.finalize_workflow(elapsed_time=duration)

                downstream_success = self._resolve_downstream_workflows()
                if not downstream_success:
                    return None

                return ("success", {})

            except Exception as e:
                duration = (datetime.now() - workflow_start).total_seconds()
                self.state.failed = True
                # Enrich BEFORE firing the error event so the formatter
                # has full context when it renders the user-facing message.
                if not hasattr(e, "context") or not isinstance(e.context, dict):  # type: ignore[attr-defined]
                    e.context = {}  # type: ignore[attr-defined]
                e.context.update(  # type: ignore[attr-defined]
                    {
                        "workflow": self.metadata.agent_name,
                        "operation": "async_workflow_execution",
                    }
                )
                self.event_logger.handle_workflow_error(e, elapsed_time=duration)
                raise

    def run(self):
        """Execute workflow sequentially."""
        should_continue = self._resolve_upstream_and_initialize()
        if should_continue is False:
            return None

        workflow_start = datetime.now()
        self.event_logger.log_workflow_start(workflow_start, is_async=False)

        return self._run_workflow_with_context(workflow_start)

    def _run_workflow_with_context(self, workflow_start):
        """Execute workflow with retry tracking context active."""
        manager = get_manager()
        with manager.context():
            try:
                total_actions = len(self.execution_order)
                self.console.print(f"Found {total_actions} actions to run.")

                for idx, action_name in enumerate(self.execution_order):
                    manager.set_context(action_name=action_name, action_index=idx)

                    should_stop = self._run_single_action(idx, action_name, total_actions)
                    if should_stop:
                        break

                if self.services.core.state_manager.is_workflow_complete():
                    duration = (datetime.now() - workflow_start).total_seconds()
                    self.event_logger.finalize_workflow(elapsed_time=duration)

                    downstream_success = self._resolve_downstream_workflows()
                    if not downstream_success:
                        return None

                    return ("success", {})

                return None

            except Exception as e:
                duration = (datetime.now() - workflow_start).total_seconds()
                self.state.failed = True
                # Enrich BEFORE firing the error event so the formatter
                # has full context when it renders the user-facing message.
                if not hasattr(e, "context") or not isinstance(e.context, dict):  # type: ignore[attr-defined]
                    e.context = {}  # type: ignore[attr-defined]
                e.context.update(  # type: ignore[attr-defined]
                    {
                        "workflow": self.metadata.agent_name,
                        "operation": "sequential_workflow_execution",
                    }
                )
                self.event_logger.handle_workflow_error(e, elapsed_time=duration)
                raise

    def _run_single_action(self, idx: int, action_name: str, total_actions: int) -> bool:
        """Run a single action in sequential mode. Return True if workflow should stop."""
        action_config = self.action_configs[action_name]
        start_time = datetime.now()

        self.event_logger.fire_action_start(idx, action_name, total_actions, action_config)

        if self.services.core.state_manager.is_completed(action_name):
            if self.services.core.action_executor.verify_completion_status(action_name):
                self.event_logger.log_action_skip(idx, action_name, total_actions)
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
            )
        )

        if result.success:
            if result.status == "batch_submitted":
                return True

            if result.output_folder and result.status == "completed":
                self.state.ephemeral_directories.append(
                    {
                        "output_folder": result.output_folder,
                        "ephemeral": action_config.get("ephemeral", False),
                    }
                )
            return False

        raise result.error
