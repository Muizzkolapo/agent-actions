"""
Agent workflow orchestration.
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from rich.console import Console

from agent_actions.config.factory import create_agent_runner
from agent_actions.errors import get_error_detail
from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.input.loaders.udf import discover_udfs
from agent_actions.llm.realtime.config import ConfigManager
from agent_actions.logging import fire_event, get_manager
from agent_actions.logging.events import (
    AgentCompleteEvent,
    AgentFailedEvent,
    AgentSkipEvent,
    AgentStartEvent,
    UDFDiscoveryCompleteEvent,
    UDFDiscoveryStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    WorkflowInitializationStartEvent,
    WorkflowServicesInitializationStartEvent,
    WorkflowStartEvent,
)
from agent_actions.storage import get_storage_backend
from agent_actions.utils.module_loader import ensure_path_importable

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.workflow.executor import AgentExecutor, ExecutorDependencies
from agent_actions.workflow.managers.artifacts import ArtifactLinker
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.loop import VersionOutputCorrelator
from agent_actions.workflow.managers.manifest import ManifestManager
from agent_actions.workflow.managers.output import AgentOutputManager, OutputManagerConfig
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import AgentStateManager
from agent_actions.workflow.models import (
    AgentLogParams,
    CoreServices,
    RuntimeContext,
    SupportServices,
    WorkflowConfig,
    WorkflowMetadata,
    WorkflowPaths,
    WorkflowServices,
    WorkflowState,
)
from agent_actions.workflow.parallel.action_executor import (
    ActionLevelOrchestrator,
    LevelExecutionParams,
)
from agent_actions.workflow.parallel.dependency import (
    WorkflowDependencyOrchestrator,
)

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """Orchestrates multi-agent workflow execution."""

    def __init__(self, config: WorkflowConfig):
        """Initialize workflow with configuration and dependencies."""
        fire_event(
            WorkflowInitializationStartEvent(
                workflow_name=config.manager.agent_name if config.manager else "unknown"
            )
        )

        self.config = config
        self.runtime = RuntimeContext(state=WorkflowState(), console=Console())

        if config.manager is None:
            config.manager = ConfigManager(
                config.paths.constructor_path,
                config.paths.default_path,
                project_root=config.project_root,
            )
        self._load_configs()

        self._validate_schema_files()

        self.storage_backend: StorageBackend | None = self._initialize_storage_backend()
        self.services = self._initialize_services()
        self._init_dependency_orchestrator()
        self.workflow_session_id = self._generate_workflow_session_id()
        self._inject_workflow_session_id()

    @property
    def state(self):
        """Return workflow state from runtime context."""
        return self.runtime.state

    @property
    def console(self):
        """Return console from runtime context."""
        return self.runtime.console

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
            WorkflowConfig(
                paths=WorkflowPaths(
                    constructor_path=config_path,
                    user_code_path=user_code_path,
                    default_path=default_path,
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
        # Assumes: .../workflows/CURRENT/agent_config/current.yml
        return current_config_path.parents[2]

    def _initialize_services(self) -> WorkflowServices:
        """Initialize all workflow services."""
        fire_event(WorkflowServicesInitializationStartEvent(workflow_name=self.agent_name))

        agent_runner = create_agent_runner(
            use_tools=self.config.use_tools,
            storage_backend=self.storage_backend,
        )
        agent_runner.execution_order = self.execution_order
        agent_runner.agent_indices = self.agent_indices
        agent_runner.agent_configs = self.agent_configs
        agent_runner.workflow_name = self.agent_name
        agent_runner.project_root = self.config.project_root

        workflow_defaults = self.config.manager.user_config.get("defaults") or {}
        agent_runner.data_source_config = workflow_defaults.get("data_source")

        from agent_actions.llm.batch.service import BatchService  # avoid circular import

        batch_service = BatchService(
            agent_indices=self.agent_indices,
            dependency_configs=self.agent_configs,
            storage_backend=self.storage_backend,
            action_name=self.agent_name,
        )

        agent_folder = Path(
            agent_runner.get_agent_folder(self.agent_name, project_root=self.config.project_root)
        )
        self._agent_folder = agent_folder
        status_file = agent_folder / ".agent_status.json"

        version_correlator = VersionOutputCorrelator(
            agent_folder,
            storage_backend=agent_runner.storage_backend,
        )

        state_manager = AgentStateManager(status_file, self.execution_order)
        skip_evaluator = SkipEvaluator(self.console)
        batch_manager = BatchLifecycleManager(
            batch_service, self.console, storage_backend=self.storage_backend
        )
        output_manager = AgentOutputManager(
            OutputManagerConfig(
                agent_folder=agent_folder,
                execution_order=self.execution_order,
                agent_configs=self.agent_configs,
                agent_status=state_manager.agent_status,
                version_correlator=version_correlator,
                console=self.console,
                storage_backend=agent_runner.storage_backend,
                data_source_config=agent_runner.data_source_config,
            )
        )

        agent_executor = AgentExecutor(
            ExecutorDependencies(
                agent_runner=agent_runner,
                state_manager=state_manager,
                skip_evaluator=skip_evaluator,
                batch_manager=batch_manager,
                output_manager=output_manager,
            ),
            console=self.console,
        )

        action_level_orchestrator = ActionLevelOrchestrator(
            self.execution_order, self.agent_configs, self.console
        )

        agent_io_path = agent_folder
        manifest_manager = ManifestManager(agent_io_path)

        levels = action_level_orchestrator.compute_execution_levels()
        manifest_manager.initialize_manifest(
            workflow_name=self.agent_name,
            execution_order=self.execution_order,
            levels=levels,
            agent_configs=self.agent_configs,
        )

        agent_runner.manifest_manager = manifest_manager

        return WorkflowServices(
            core=CoreServices(
                agent_runner=agent_runner,
                state_manager=state_manager,
                agent_executor=agent_executor,
                action_level_orchestrator=action_level_orchestrator,
            ),
            support=SupportServices(
                batch_service=batch_service,
                version_correlator=version_correlator,
                skip_evaluator=skip_evaluator,
                batch_manager=batch_manager,
                output_manager=output_manager,
                manifest_manager=manifest_manager,
            ),
        )

    def _load_configs(self):
        """Load and process configuration files."""
        manager = self.config.manager
        manager.load_configs()
        manager.validate_agent_name()
        manager.check_child_pipeline()

        # Discover UDFs BEFORE expanding actions (which needs UDF metadata)
        self._discover_udfs()

        user_agents = manager.get_user_agents()
        manager.merge_agent_configs(user_agents)
        manager.determine_execution_order()

        execution_order = manager.execution_order
        agent_configs = manager.get_all_agent_configs_as_dicts()
        agent_indices = {agent: i for i, agent in enumerate(execution_order)}

        # Add idx and workflow_config_path fields to each agent config
        for agent_name, agent_config in agent_configs.items():
            # Skip None configs (defensive check for malformed dictionaries)
            if agent_config is None:
                continue
            if agent_name in agent_indices:
                agent_config["idx"] = agent_indices[agent_name]
            # Add workflow config path for static data loading
            agent_config["workflow_config_path"] = self.config.paths.constructor_path
            if self.config.project_root:
                agent_config["_project_root"] = str(self.config.project_root)

        # Create metadata object
        self.metadata = WorkflowMetadata(
            agent_name=manager.agent_name,
            execution_order=execution_order,
            agent_indices=agent_indices,
            agent_configs=agent_configs,
            child_pipeline=manager.child_pipeline,
        )

    def _validate_schema_files(self) -> None:
        """Validate that all referenced schema files exist (fail-fast).

        Raises:
            ConfigValidationError: If any referenced schema files are missing.
        """
        manager = self.config.manager
        project_root = (
            (manager.project_root if manager else None) or self.config.project_root or Path.cwd()
        )
        schema_dir = project_root / "schema"

        # Collect all missing schemas with their action names
        missing_schemas = []

        for action_name, agent_config in self.agent_configs.items():
            if agent_config is None:
                continue

            # Check for schema_name field (the standard way to reference schemas)
            schema_name = agent_config.get("schema_name")
            if schema_name:
                schema_file = schema_dir / f"{schema_name}.yml"
                if not schema_file.exists():
                    missing_schemas.append((action_name, schema_name, schema_file))

        # Raise error if any schemas are missing
        if missing_schemas:
            error_lines = ["Schema validation failed. The following schema files are missing:"]
            for action_name, schema_name, schema_file in missing_schemas:
                error_lines.append(f"  - Action '{action_name}': schema '{schema_name}.yml'")
                error_lines.append(f"    Expected at: {schema_file}")

            error_lines.append("")
            error_lines.append("Please ensure all schema files exist in the schema/ directory.")

            raise ConfigValidationError(
                "\n".join(error_lines),
                context={
                    "missing_schemas": [
                        {"action": a, "schema": s, "path": str(p)} for a, s, p in missing_schemas
                    ],
                    "schema_dir": str(schema_dir),
                },
            )

    def _initialize_storage_backend(self) -> Optional["StorageBackend"]:
        """Initialize the SQLite storage backend for the workflow."""
        try:
            # Get workflow directory from config path
            config_path = Path(self.config.paths.constructor_path)
            # Assumes: .../workflows/WORKFLOW/agent_config/current.yml
            workflow_dir = config_path.parents[1]

            backend = get_storage_backend(
                workflow_path=str(workflow_dir),
                workflow_name=self.metadata.agent_name,
                backend_type="sqlite",
            )
            backend.initialize()

            db_path = workflow_dir / "agent_io" / "target" / f"{self.metadata.agent_name}.db"
            self.console.print(f"[cyan]📦 Storage backend: {db_path}[/cyan]")
            return backend
        except (OSError, ValueError) as e:
            # Storage backend is required - no fallback
            logger.error(
                "Storage backend initialization failed: %s",
                e,
                extra={"workflow_name": self.metadata.agent_name},
            )
            self.console.print(f"[red]❌ Storage backend failed: {e}[/red]")
            raise

    @property
    def agent_name(self) -> str:
        """Return agent name from metadata."""
        return self.metadata.agent_name

    @property
    def execution_order(self) -> list:
        """Return execution order from metadata."""
        return self.metadata.execution_order

    @property
    def agent_indices(self) -> dict:
        """Return agent indices from metadata."""
        return self.metadata.agent_indices

    @property
    def agent_configs(self) -> dict:
        """Return agent configs from metadata."""
        return self.metadata.agent_configs

    @property
    def child_pipeline(self) -> str | None:
        """Return child pipeline from metadata."""
        return self.metadata.child_pipeline

    def _discover_udfs(self):
        """Discover user-defined functions from configured paths."""
        total_udfs = 0
        if self.config.paths.user_code_path:
            total_udfs = self._discover_udfs_from_path(self.config.paths.user_code_path)
        elif self.config.manager.tool_path:
            for path in self.config.manager.tool_path:
                count = self._discover_udfs_from_path(path)
                total_udfs += count

        # Fire UDF discovery complete event once with total count
        if total_udfs > 0:
            self.console.print(f"[green]✅ Discovered {total_udfs} Tools[/green]")
            fire_event(UDFDiscoveryCompleteEvent(total_udfs=total_udfs))

    def _discover_udfs_from_path(self, path: str) -> int:
        """Discover UDFs from a specific path."""
        p = Path(path)
        if p.is_absolute():
            abs_path = p
        elif self.config.project_root:
            abs_path = (self.config.project_root / p).resolve()
        else:
            abs_path = p.absolute()

        if abs_path.exists() and abs_path.is_dir():
            # Fire UDF discovery start event
            fire_event(UDFDiscoveryStartEvent(search_path=str(abs_path)))

            # Use centralized path management (thread-safe, cached)
            ensure_path_importable(abs_path)

            self.console.print(f"[cyan]🔍 Discovering Tools in {abs_path}...[/cyan]")

            registry = discover_udfs(abs_path)

            # Don't fire complete event here - it's fired once in _discover_udfs()
            return len(registry)

        return 0

    def _generate_workflow_session_id(self) -> str:
        """Generate a deterministic workflow session ID from config path + agent name."""
        config_content = f"{self.config.paths.constructor_path}:{self.agent_name}"
        config_hash = hashlib.sha256(config_content.encode()).hexdigest()[:16]
        return f"workflow_{config_hash}"

    def _inject_workflow_session_id(self):
        """Inject workflow session ID into all agent configurations."""
        from agent_actions.utils.correlation import VersionIdGenerator

        VersionIdGenerator.clear_version_correlation_registry()

        for agent_config in self.agent_configs.values():
            agent_config["workflow_session_id"] = self.workflow_session_id

    def _resolve_upstream_workflows(self) -> bool:
        """Recursively resolve and execute upstream dependencies."""
        if not self.config.run_upstream:
            return True
        return self.dependency_orchestrator.resolve_upstream_workflows(
            agent_configs=self.agent_configs,
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

    def _log_workflow_start(self, workflow_start: datetime, is_async: bool = False):
        """Log workflow start with session separator."""
        correlation_id = get_manager().get_context("correlation_id")
        time_str = workflow_start.strftime("%H:%M:%S.%f")[:-3]
        corr_id = correlation_id[:8] if correlation_id else "unknown"
        separator = f"====== {time_str} | {corr_id} ======"
        logger.info(separator)

        mode = "async" if is_async else "sequential"

        # Fire workflow start event
        fire_event(
            WorkflowStartEvent(
                workflow_name=self.agent_name,
                agent_count=len(self.execution_order),
                execution_mode=mode,
                run_upstream=self.config.run_upstream,
                run_downstream=self.config.run_downstream,
            )
        )

        logger.info(
            "Workflow started (%s)",
            mode,
            extra={
                "operation": f"workflow_start_{mode}",
                "workflow_name": self.agent_name,
                "agent_count": len(self.execution_order),
            },
        )

    def _resolve_upstream_and_initialize(self) -> bool | None:
        """Initialize event context and resolve upstream dependencies.

        Returns:
            True to continue, False if upstream has pending batches.
        """
        # Set workflow context with correlation ID
        get_manager().set_context(workflow_name=self.agent_name, correlation_id=str(uuid4())[:8])

        should_continue = self._resolve_upstream_workflows()
        if not should_continue:
            # Upstream has pending batch jobs, exit gracefully
            return False
        return True

    async def async_run(self, concurrency_limit: int = 5):
        """Execute workflow level-by-level with parallelism within each level."""
        # Initialize event context and resolve upstream
        should_continue = self._resolve_upstream_and_initialize()
        if should_continue is False:
            return None

        workflow_start = datetime.now()
        self._log_workflow_start(workflow_start, is_async=True)

        # Use context manager to save/restore context
        manager = get_manager()
        with manager.context():
            try:
                levels = self.services.core.action_level_orchestrator.compute_execution_levels()
                self.services.core.action_level_orchestrator.log_execution_levels(
                    levels, self.agent_indices
                )

                # Execute each level
                for level_idx, level_agents in enumerate(levels):
                    # Set agent context for each agent in the level
                    for agent_name in level_agents:
                        if agent_name in self.agent_indices:
                            manager.set_context(
                                agent_name=agent_name, agent_index=self.agent_indices[agent_name]
                            )

                    orchestrator = self.services.core.action_level_orchestrator
                    level_complete = await orchestrator.execute_level_async(
                        LevelExecutionParams(
                            level_idx=level_idx,
                            level_agents=level_agents,
                            agent_indices=self.agent_indices,
                            state_manager=self.services.core.state_manager,
                            agent_executor=self.services.core.agent_executor,
                            concurrency_limit=concurrency_limit,
                        )
                    )

                    # If batch jobs pending, stop workflow
                    if not level_complete:
                        return

                # Workflow complete
                duration = (datetime.now() - workflow_start).total_seconds()
                self._finalize_workflow(elapsed_time=duration)

                # Execute downstream workflows if requested
                downstream_success = self._resolve_downstream_workflows()
                if not downstream_success:
                    # Downstream has pending batch jobs
                    return None

                # Return success tuple to distinguish from batch pending (None)
                return ("success", {})

            except Exception as e:
                duration = (datetime.now() - workflow_start).total_seconds()
                self._handle_workflow_error(e, elapsed_time=duration)
                raise

    def run(self):
        """Execute workflow sequentially."""
        # Initialize event context and resolve upstream
        should_continue = self._resolve_upstream_and_initialize()
        if should_continue is False:
            return None

        workflow_start = datetime.now()
        self._log_workflow_start(workflow_start, is_async=False)

        return self._run_workflow_with_context(workflow_start)

    def _run_workflow_with_context(self, workflow_start):
        """Execute workflow with retry tracking context active."""
        # Use context manager to save/restore context
        manager = get_manager()
        with manager.context():
            try:
                total_agents = len(self.execution_order)
                self.console.print(f"Found {total_agents} agents to run.")

                for idx, agent_name in enumerate(self.execution_order):
                    # Set agent context
                    manager.set_context(agent_name=agent_name, agent_index=idx)

                    should_stop = self._run_single_agent(idx, agent_name, total_agents)
                    if should_stop:
                        # Batch submitted or workflow needs to stop
                        break

                # Check if workflow is complete
                if self.services.core.state_manager.is_workflow_complete():
                    duration = (datetime.now() - workflow_start).total_seconds()
                    self._finalize_workflow(elapsed_time=duration)

                    # Execute downstream workflows if requested
                    downstream_success = self._resolve_downstream_workflows()
                    if not downstream_success:
                        # Downstream has pending batch jobs
                        return None

                    # Return success tuple to distinguish from batch pending (None)
                    return ("success", {})

                # Workflow incomplete (batch jobs pending or stopped early)
                return None

            except Exception as e:
                duration = (datetime.now() - workflow_start).total_seconds()
                self._handle_workflow_error(e, elapsed_time=duration)
                raise

    def _run_single_agent(self, idx: int, agent_name: str, total_agents: int) -> bool:
        """Run a single agent in sequential mode. Return True if workflow should stop."""
        agent_config = self.agent_configs[agent_name]
        start_time = datetime.now()

        fire_event(
            AgentStartEvent(
                agent_name=agent_name,
                agent_index=idx,
                total_agents=total_agents,
                agent_type=agent_config.get("type", ""),
            )
        )

        if self.services.core.state_manager.is_completed(agent_name):
            self._log_agent_skip(idx, agent_name, total_agents, start_time)
            return False

        is_last = idx == len(self.execution_order) - 1
        result = self.services.core.agent_executor.execute_agent_sync(
            agent_name, agent_idx=idx, agent_config=agent_config, is_last_agent=is_last
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        self._log_agent_result(
            AgentLogParams(
                idx=idx,
                agent_name=agent_name,
                total_agents=total_agents,
                result=result,
                end_time=end_time,
                duration=duration,
            )
        )

        if result.success:
            # If batch was submitted, stop workflow to wait for completion
            if result.status == "batch_submitted":
                return True  # Signal to stop workflow

            if result.output_folder and result.status == "completed":
                self.state.ephemeral_directories.append(
                    {
                        "output_folder": result.output_folder,
                        "ephemeral": agent_config.get("ephemeral", False),
                    }
                )
            return False  # Continue to next agent

        raise result.error

    def _log_agent_skip(self, idx: int, agent_name: str, total_agents: int, _start_time: datetime):
        """Log skipped agent."""
        fire_event(
            AgentSkipEvent(
                agent_name=agent_name,
                agent_index=idx,
                total_agents=total_agents,
                skip_reason="already completed",
            )
        )

    def _log_agent_result(self, params: AgentLogParams):
        """Log agent execution result via event system."""
        if params.result.success and params.result.status == "completed":
            tokens = {}
            if hasattr(params.result, "tokens") and params.result.tokens:
                tokens = params.result.tokens
            fire_event(
                AgentCompleteEvent(
                    agent_name=params.agent_name,
                    agent_index=params.idx,
                    total_agents=params.total_agents,
                    execution_time=params.duration,
                    output_path=params.result.output_folder or "",
                    tokens=tokens,
                )
            )
        elif not params.result.success:
            fire_event(
                AgentFailedEvent(
                    agent_name=params.agent_name,
                    agent_index=params.idx,
                    total_agents=params.total_agents,
                    error_message=str(params.result.error) if params.result.error else "",
                    error_detail=get_error_detail(params.result.error)
                    if params.result.error
                    else "",
                    error_type=type(params.result.error).__name__ if params.result.error else "",
                    execution_time=params.duration,
                )
            )
        # batch_submitted: BatchSubmittedEvent already fired by executor

    def _finalize_workflow(self, elapsed_time: float = 0.0):
        """Finalize workflow execution."""
        summary = self.services.core.state_manager.get_summary()

        fire_event(
            WorkflowCompleteEvent(
                workflow_name=self.agent_name,
                elapsed_time=elapsed_time,
                agents_completed=summary.get("completed", 0),
                agents_skipped=summary.get("skipped", 0),
                agents_failed=summary.get("failed", 0),
            )
        )

        if self.services.support.manifest_manager:
            self.services.support.manifest_manager.mark_workflow_completed()

    def _handle_workflow_error(self, error: Exception, elapsed_time: float = 0.0):
        """Handle workflow execution error with structured output."""
        self.state.failed = True

        fire_event(
            WorkflowFailedEvent(
                workflow_name=self.agent_name,
                error_message=str(error),
                error_detail=get_error_detail(error),
                error_type=type(error).__name__,
                elapsed_time=elapsed_time,
                failed_agent=get_manager().get_context("agent_name") or "",
            )
        )

        if self.services.support.manifest_manager:
            self.services.support.manifest_manager.mark_workflow_failed(get_error_detail(error))

        self.services.core.state_manager.mark_running_as_failed()

        # CLI decorator checks this attribute to prevent duplicate output
        error._already_displayed = True
