"""Service assembly and storage initialization for workflow startup."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from agent_actions.config.factory import create_agent_runner
from agent_actions.storage import get_storage_backend
from agent_actions.workflow.executor import AgentExecutor, ExecutorDependencies
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.loop import VersionOutputCorrelator
from agent_actions.workflow.managers.manifest import ManifestManager
from agent_actions.workflow.managers.output import AgentOutputManager, OutputManagerConfig
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import AgentStateManager
from agent_actions.workflow.models import (
    CoreServices,
    SupportServices,
    WorkflowConfig,
    WorkflowMetadata,
    WorkflowServices,
)
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

from agent_actions.logging import fire_event
from agent_actions.logging.events import WorkflowServicesInitializationStartEvent

logger = logging.getLogger(__name__)


def initialize_storage_backend(
    config: WorkflowConfig,
    metadata: WorkflowMetadata,
    console: Console,
) -> "StorageBackend | None":
    """Initialize the SQLite storage backend for the workflow."""
    try:
        config_path = Path(config.paths.constructor_path)
        # Assumes: .../workflows/WORKFLOW/agent_config/current.yml
        workflow_dir = config_path.parents[1]

        backend = get_storage_backend(
            workflow_path=str(workflow_dir),
            workflow_name=metadata.agent_name,
            backend_type="sqlite",
        )
        backend.initialize()

        db_path = workflow_dir / "agent_io" / "target" / f"{metadata.agent_name}.db"
        console.print(f"[cyan]\U0001f4e6 Storage backend: {db_path}[/cyan]")
        return backend
    except (OSError, ValueError) as e:
        logger.error(
            "Storage backend initialization failed: %s",
            e,
            extra={"workflow_name": metadata.agent_name},
        )
        console.print(f"[red]\u274c Storage backend failed: {e}[/red]")
        raise


def initialize_services(
    metadata: WorkflowMetadata,
    config: WorkflowConfig,
    storage_backend: "StorageBackend | None",
    console: Console,
) -> tuple[WorkflowServices, Path]:
    """Initialize all workflow services.

    Returns:
        A ``(services, agent_folder)`` tuple.
    """
    fire_event(WorkflowServicesInitializationStartEvent(workflow_name=metadata.agent_name))

    agent_runner = create_agent_runner(
        use_tools=config.use_tools,
        storage_backend=storage_backend,
    )
    agent_runner.execution_order = metadata.execution_order
    agent_runner.agent_indices = metadata.agent_indices
    agent_runner.agent_configs = metadata.agent_configs
    agent_runner.workflow_name = metadata.agent_name
    agent_runner.project_root = config.project_root

    workflow_defaults = config.manager.user_config.get("defaults") or {}
    agent_runner.data_source_config = workflow_defaults.get("data_source")

    from agent_actions.llm.batch.service import BatchService  # avoid circular import

    batch_service = BatchService(
        agent_indices=metadata.agent_indices,
        dependency_configs=metadata.agent_configs,
        storage_backend=storage_backend,
        action_name=metadata.agent_name,
    )

    agent_folder = Path(
        agent_runner.get_agent_folder(metadata.agent_name, project_root=config.project_root)
    )
    status_file = agent_folder / ".agent_status.json"

    version_correlator = VersionOutputCorrelator(
        agent_folder,
        storage_backend=agent_runner.storage_backend,
    )

    state_manager = AgentStateManager(status_file, metadata.execution_order)
    skip_evaluator = SkipEvaluator(console)
    batch_manager = BatchLifecycleManager(batch_service, console, storage_backend=storage_backend)
    output_manager = AgentOutputManager(
        OutputManagerConfig(
            agent_folder=agent_folder,
            execution_order=metadata.execution_order,
            agent_configs=metadata.agent_configs,
            agent_status=state_manager.agent_status,
            version_correlator=version_correlator,
            console=console,
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
        console=console,
    )

    action_level_orchestrator = ActionLevelOrchestrator(
        metadata.execution_order, metadata.agent_configs, console
    )

    manifest_manager = ManifestManager(agent_folder)

    levels = action_level_orchestrator.compute_execution_levels()
    manifest_manager.initialize_manifest(
        workflow_name=metadata.agent_name,
        execution_order=metadata.execution_order,
        levels=levels,
        agent_configs=metadata.agent_configs,
    )

    agent_runner.manifest_manager = manifest_manager

    services = WorkflowServices(
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

    return services, agent_folder
