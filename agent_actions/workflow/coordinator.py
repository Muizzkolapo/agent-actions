"""Agent workflow orchestration."""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from rich.console import Console

from agent_actions.logging import get_manager
from agent_actions.workflow.config_pipeline import load_workflow_configs, validate_schema_files
from agent_actions.workflow.execution_events import WorkflowEventLogger
from agent_actions.workflow.managers.artifacts import ArtifactLinker
from agent_actions.workflow.models import (
    AgentLogParams,
    RuntimeContext,
    WorkflowConfig,
    WorkflowPaths,
    WorkflowState,
)
from agent_actions.workflow.parallel.dependency import WorkflowDependencyOrchestrator
from agent_actions.workflow.service_init import initialize_services, initialize_storage_backend

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """Orchestrates multi-agent workflow execution."""

    def __init__(self, config: WorkflowConfig):
        """Initialize workflow with configuration and dependencies."""
        self.config = config
        self.runtime = RuntimeContext(state=WorkflowState(), console=Console())

        # Config pipeline (fires WorkflowInitializationStartEvent internally)
        self.metadata = load_workflow_configs(config, self.console)
        validate_schema_files(self.agent_configs, self.config)

        # Storage & services
        self.storage_backend = initialize_storage_backend(config, self.metadata, self.console)
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

    # ── Session management ──────────────────────────────────────────────

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

    # ── Upstream / downstream resolution ────────────────────────────────

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
                    levels, self.agent_indices
                )

                from agent_actions.workflow.parallel.action_executor import LevelExecutionParams

                for level_idx, level_agents in enumerate(levels):
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
                total_agents = len(self.execution_order)
                self.console.print(f"Found {total_agents} agents to run.")

                for idx, agent_name in enumerate(self.execution_order):
                    manager.set_context(agent_name=agent_name, agent_index=idx)

                    should_stop = self._run_single_agent(idx, agent_name, total_agents)
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
                self.event_logger.handle_workflow_error(e, elapsed_time=duration)
                raise

    def _run_single_agent(self, idx: int, agent_name: str, total_agents: int) -> bool:
        """Run a single agent in sequential mode. Return True if workflow should stop."""
        agent_config = self.agent_configs[agent_name]
        start_time = datetime.now()

        self.event_logger.fire_agent_start(idx, agent_name, total_agents, agent_config)

        if self.services.core.state_manager.is_completed(agent_name):
            self.event_logger.log_agent_skip(idx, agent_name, total_agents)
            return False

        is_last = idx == len(self.execution_order) - 1
        result = self.services.core.agent_executor.execute_agent_sync(
            agent_name, agent_idx=idx, agent_config=agent_config, is_last_agent=is_last
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        self.event_logger.log_agent_result(
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
            if result.status == "batch_submitted":
                return True

            if result.output_folder and result.status == "completed":
                self.state.ephemeral_directories.append(
                    {
                        "output_folder": result.output_folder,
                        "ephemeral": agent_config.get("ephemeral", False),
                    }
                )
            return False

        raise result.error
