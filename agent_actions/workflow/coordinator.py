"""
Agent workflow orchestration.
"""

import hashlib
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console

from agent_actions.config.factory import create_agent_runner
from agent_actions.input.loaders.udf import discover_udfs
from agent_actions.utils.module_loader import ensure_path_importable
from agent_actions.llm.realtime.config import ConfigManager
from agent_actions.logging import CorrelationContext, fire_event
from agent_actions.logging.events import (
    WorkflowStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    AgentStartEvent,
    AgentCompleteEvent,
    AgentSkipEvent,
    AgentFailedEvent,
)
from agent_actions.workflow.parallel.action_executor import (
    ActionLevelOrchestrator,
    LevelExecutionParams,
)
from agent_actions.workflow.executor import AgentExecutor, ExecutorDependencies
from agent_actions.workflow.managers.artifacts import ArtifactLinker
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.loop import VersionOutputCorrelator
from agent_actions.workflow.managers.manifest import ManifestManager
from agent_actions.workflow.managers.output import AgentOutputManager, OutputManagerConfig
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import AgentStateManager
from agent_actions.workflow.parallel.dependency import (
    WorkflowDependencyOrchestrator,
)
from agent_actions.workflow.models import (
    WorkflowPaths,
    WorkflowConfig,
    WorkflowState,
    RuntimeContext,
    WorkflowMetadata,
    AgentLogParams,
    CoreServices,
    SupportServices,
    WorkflowServices,
)

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """
    Orchestrates multi-agent workflow execution.

    This refactored version delegates complexity to specialized modules:
    - AgentStateManager: Status persistence and queries
    - SkipEvaluator: Skip condition evaluation (strategy pattern)
    - BatchLifecycleManager: Batch job handling
    - AgentOutputManager: Output loading and passthrough
    - AgentExecutor: Single agent execution
    - ActionLevelOrchestrator: Parallel execution coordination by action level
    """

    def __init__(self, config: WorkflowConfig):
        """Initialize workflow with configuration and dependencies."""
        # Store configuration
        self.config = config
        self.runtime = RuntimeContext(state=WorkflowState(), console=Console())

        # Load configuration
        if config.manager is None:
            config.manager = ConfigManager(config.paths.constructor_path, config.paths.default_path)
        self._load_configs()

        # Initialize services
        self.services = self._initialize_services()

        # Initialize dependency orchestration (for upstream/downstream workflows)
        self._init_dependency_orchestrator()

        # Generate and inject workflow session ID
        self.workflow_session_id = self._generate_workflow_session_id()
        self._inject_workflow_session_id()

    @property
    def state(self):
        """Get workflow state from runtime context."""
        return self.runtime.state

    @property
    def console(self):
        """Get console from runtime context."""
        return self.runtime.console

    @property
    def _workspace_index(self):
        """Get or create workspace index (lazy initialization)."""
        if not hasattr(self, "_workspace_index_cached"):
            self._workspace_index_cached = None
        return self._workspace_index_cached

    @_workspace_index.setter
    def _workspace_index(self, value):
        """Set workspace index."""
        self._workspace_index_cached = value

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
        user_code_path: Optional[str],
        default_path: Optional[str],
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
            )
        )

    def _get_workflows_root(self) -> Path:
        """Get the root directory containing all workflows."""
        current_config_path = Path(self.config.paths.constructor_path)
        # Assumes: .../workflows/CURRENT/agent_config/current.yml
        return current_config_path.parents[2]

    def _initialize_services(self) -> WorkflowServices:
        """Initialize all workflow services."""
        # Create agent runner
        agent_runner = create_agent_runner(
            use_tools=self.config.use_tools,
            constructor_path=self.config.paths.constructor_path,
            default_path=getattr(self.config.manager, "default_path", None),
        )
        agent_runner.execution_order = self.execution_order
        agent_runner.agent_indices = self.agent_indices
        agent_runner.agent_configs = self.agent_configs
        agent_runner.workflow_name = self.agent_name

        # Import here to avoid circular dependency
        from agent_actions.llm.batch.service import BatchService

        batch_service = BatchService(
            agent_indices=self.agent_indices, dependency_configs=self.agent_configs
        )

        # Get agent folder and store for retry tracking
        agent_folder = Path(agent_runner.get_agent_folder(self.agent_name))
        self._agent_folder = agent_folder  # Store for retry tracker context
        status_file = agent_folder / ".agent_status.json"

        # Initialize loop correlator
        loop_correlator = VersionOutputCorrelator(agent_folder)

        # Initialize modular components
        state_manager = AgentStateManager(status_file, self.execution_order)
        skip_evaluator = SkipEvaluator(self.console)
        batch_manager = BatchLifecycleManager(batch_service, self.console)
        output_manager = AgentOutputManager(
            OutputManagerConfig(
                agent_folder=agent_folder,
                execution_order=self.execution_order,
                agent_configs=self.agent_configs,
                agent_status=state_manager.agent_status,
                loop_correlator=loop_correlator,
                console=self.console,
            )
        )

        # Initialize agent executor
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

        # Initialize action-level orchestrator
        action_level_orchestrator = ActionLevelOrchestrator(
            self.execution_order, self.agent_configs, self.console
        )

        # Initialize manifest manager
        agent_io_path = agent_folder
        manifest_manager = ManifestManager(agent_io_path)

        # Compute execution levels and initialize manifest
        levels = action_level_orchestrator.compute_execution_levels()
        manifest_manager.initialize_manifest(
            workflow_name=self.agent_name,
            execution_order=self.execution_order,
            levels=levels,
            agent_configs=self.agent_configs,
        )

        # Store manifest manager for use by other components
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
                loop_correlator=loop_correlator,
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

        # Create metadata object
        self.metadata = WorkflowMetadata(
            agent_name=manager.agent_name,
            execution_order=execution_order,
            agent_indices=agent_indices,
            agent_configs=agent_configs,
            child_pipeline=manager.child_pipeline,
        )

    @property
    def agent_name(self) -> str:
        """Get agent name from metadata."""
        return self.metadata.agent_name

    @property
    def execution_order(self) -> list:
        """Get execution order from metadata."""
        return self.metadata.execution_order

    @property
    def agent_indices(self) -> dict:
        """Get agent indices from metadata."""
        return self.metadata.agent_indices

    @property
    def agent_configs(self) -> dict:
        """Get agent configs from metadata."""
        return self.metadata.agent_configs

    @property
    def child_pipeline(self) -> Optional[str]:
        """Get child pipeline from metadata."""
        return self.metadata.child_pipeline

    def _discover_udfs(self):
        """Discover user-defined functions from configured paths."""
        if self.config.paths.user_code_path:
            self._discover_udfs_from_path(self.config.paths.user_code_path, is_primary=True)
        elif self.config.manager.tool_path:
            total_udfs = 0
            for path in self.config.manager.tool_path:
                count = self._discover_udfs_from_path(path, is_primary=False)
                total_udfs += count
            if total_udfs > 0:
                self.console.print(f"[green]✅ Discovered {total_udfs} UDF(s)[/green]")

    def _discover_udfs_from_path(self, path: str, is_primary: bool) -> int:
        """Discover UDFs from a specific path."""
        abs_path = Path(path).absolute()

        if abs_path.exists() and abs_path.is_dir():
            # Use centralized path management (thread-safe, cached)
            ensure_path_importable(abs_path)

            if not is_primary:
                self.console.print(f"[cyan]🔍 Discovering UDFs in {abs_path}...[/cyan]")
            else:
                self.console.print("[cyan]🔍 Discovering UDFs...[/cyan]")

            registry = discover_udfs(abs_path)

            if is_primary:
                self.console.print(f"[green]✅ Discovered {len(registry)} UDF(s)[/green]")

            return len(registry)

        return 0

    def _generate_workflow_session_id(self) -> str:
        """Generate a deterministic yet unique workflow session ID."""
        timestamp = int(time.time())
        config_content = f"{self.config.paths.constructor_path}:{self.agent_name}"
        config_hash = hashlib.md5(config_content.encode()).hexdigest()[:8]
        return f"workflow_{timestamp}_{config_hash}"

    def _inject_workflow_session_id(self):
        """Inject workflow session ID into all agent configurations."""
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
        correlation_id = CorrelationContext.get_correlation_id()
        time_str = workflow_start.strftime("%H:%M:%S.%f")[:-3]
        corr_id = correlation_id[:8] if correlation_id else "unknown"
        separator = f"====== {time_str} | {corr_id} ======"
        logger.info(separator)

        mode = "async" if is_async else "sequential"

        # Fire workflow start event
        fire_event(WorkflowStartEvent(
            workflow_name=self.agent_name,
            agent_count=len(self.execution_order),
            execution_mode=mode,
            run_upstream=self.config.run_upstream,
            run_downstream=self.config.run_downstream,
        ))

        logger.info(
            "Workflow started (%s)",
            mode,
            extra={
                "operation": f"workflow_start_{mode}",
                "workflow_name": self.agent_name,
                "agent_count": len(self.execution_order),
            },
        )

    def _resolve_upstream_and_initialize(self) -> Optional[bool]:
        """
        Initialize correlation context and resolve upstream dependencies.

        Returns:
            True if should continue, False if upstream has pending batches,
            None if exception occurred (caller should re-raise)
        """
        previous_context = CorrelationContext.get_context()
        try:
            CorrelationContext.start_workflow(self.agent_name)
            should_continue = self._resolve_upstream_workflows()
            if not should_continue:
                # Upstream has pending batch jobs, exit gracefully
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

    async def async_run(self, concurrency_limit: int = 5):
        """
        Execute workflow level-by-level with parallelism within each level.

        Args:
            concurrency_limit: Maximum concurrent agents within a level (default 5)
        """
        # Initialize correlation context and resolve upstream
        should_continue = self._resolve_upstream_and_initialize()
        if should_continue is False:
            return None

        previous_context = CorrelationContext.get_context()
        workflow_start = datetime.now()
        self._log_workflow_start(workflow_start, is_async=True)

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
                        CorrelationContext.set_agent(agent_name, self.agent_indices[agent_name])

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
        finally:
            # Restore previous context
            if previous_context:
                CorrelationContext.set_context(previous_context)
            else:
                CorrelationContext.clear_context()

    def run(self):
        """Execute workflow sequentially."""
        # Initialize correlation context and resolve upstream
        should_continue = self._resolve_upstream_and_initialize()
        if should_continue is False:
            return None

        previous_context = CorrelationContext.get_context()
        workflow_start = datetime.now()
        self._log_workflow_start(workflow_start, is_async=False)

        return self._run_workflow_with_context(previous_context, workflow_start)

    def _run_workflow_with_context(self, previous_context, workflow_start):
        """Execute workflow with retry tracking context active."""
        try:
            total_agents = len(self.execution_order)
            self.console.print(f"Found {total_agents} agents to run.")

            for idx, agent_name in enumerate(self.execution_order):
                # Set agent context for correlation
                CorrelationContext.set_agent(agent_name, idx)

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
        finally:
            # Restore previous context
            if previous_context:
                CorrelationContext.set_context(previous_context)
            else:
                CorrelationContext.clear_context()

    def _run_single_agent(self, idx: int, agent_name: str, total_agents: int) -> bool:
        """
        Run a single agent in sequential mode.

        Returns:
            bool: True if workflow should stop, False to continue
        """
        agent_config = self.agent_configs[agent_name]
        start_time = datetime.now()

        # Fire agent start event
        fire_event(AgentStartEvent(
            agent_name=agent_name,
            agent_index=idx,
            total_agents=total_agents,
            agent_type=agent_config.get("type", ""),
        ))

        # Check if already completed
        if self.services.core.state_manager.is_completed(agent_name):
            self._log_agent_skip(idx, agent_name, total_agents, start_time)
            return False

        # Execute agent
        is_last = idx == len(self.execution_order) - 1
        result = self.services.core.agent_executor.execute_agent_sync(
            agent_name, agent_idx=idx, agent_config=agent_config, is_last_agent=is_last
        )

        # Log result
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

        # Handle result
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

    def _log_agent_skip(self, idx: int, agent_name: str, total_agents: int, start_time: datetime):
        """Log skipped agent."""
        # Fire agent skip event
        fire_event(AgentSkipEvent(
            agent_name=agent_name,
            agent_index=idx,
            total_agents=total_agents,
            skip_reason="already completed",
        ))

    def _get_status_display(self, status: str) -> tuple:
        """Get status display color and suffix."""
        status_map = {
            "completed": ("[green]OK[/green]", ""),
            "batch_submitted": ("[yellow]SUBMITTED[/yellow]", " (batch)"),
            "failed": ("[red]FAIL[/red]", ""),
        }
        return status_map.get(status, ("[yellow]UNKNOWN[/yellow]", ""))

    def _log_agent_result(self, params: AgentLogParams):
        """Log agent execution result via event system."""
        if params.result.success:
            # Fire agent complete event
            tokens = {}
            if hasattr(params.result, "tokens") and params.result.tokens:
                tokens = params.result.tokens
            fire_event(AgentCompleteEvent(
                agent_name=params.agent_name,
                agent_index=params.idx,
                total_agents=params.total_agents,
                execution_time=params.duration,
                output_path=params.result.output_folder or "",
                tokens=tokens,
            ))
        else:
            # Fire agent failed event
            fire_event(AgentFailedEvent(
                agent_name=params.agent_name,
                agent_index=params.idx,
                total_agents=params.total_agents,
                error_message=str(params.result.error) if params.result.error else "",
                error_type=type(params.result.error).__name__ if params.result.error else "",
                execution_time=params.duration,
            ))

    def _finalize_workflow(self, elapsed_time: float = 0.0):
        """Finalize workflow execution."""
        # Count agent statuses
        completed = 0
        skipped = 0
        failed = 0

        for agent_name in self.execution_order:
            status = self.services.core.state_manager.get_status(agent_name)
            if status == "completed":
                completed += 1
            elif status == "skipped":
                skipped += 1
            elif status == "failed":
                failed += 1

        # Fire workflow complete event
        fire_event(WorkflowCompleteEvent(
            workflow_name=self.agent_name,
            elapsed_time=elapsed_time,
            agents_completed=completed,
            agents_skipped=skipped,
            agents_failed=failed,
        ))

        # Mark workflow as completed in manifest
        if self.services.support.manifest_manager:
            self.services.support.manifest_manager.mark_workflow_completed()

    def _handle_workflow_error(self, error: Exception, elapsed_time: float = 0.0):
        """Handle workflow execution error with structured output."""
        self.state.failed = True

        # Fire workflow failed event
        fire_event(WorkflowFailedEvent(
            workflow_name=self.agent_name,
            error_message=str(error),
            error_type=type(error).__name__,
            elapsed_time=elapsed_time,
            failed_agent=CorrelationContext.get_agent_name() or "",
        ))

        # Mark workflow as failed in manifest
        if self.services.support.manifest_manager:
            self.services.support.manifest_manager.mark_workflow_failed(str(error))

        # Mark running agent as failed
        self.services.core.state_manager.mark_running_as_failed()

        # Mark exception as already displayed to prevent duplicate output
        # The CLI decorator will check for this attribute
        error._already_displayed = True
