"""Service assembly and storage initialization for workflow startup."""

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from agent_actions.config.factory import create_action_runner
from agent_actions.storage import get_storage_backend
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.loop import VersionOutputCorrelator
from agent_actions.workflow.managers.manifest import ManifestManager
from agent_actions.workflow.managers.output import ActionOutputManager, OutputManagerConfig
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager
from agent_actions.workflow.models import (
    CoreServices,
    SupportServices,
    WorkflowMetadata,
    WorkflowRuntimeConfig,
    WorkflowServices,
)
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import WorkflowServicesInitializationStartEvent

logger = logging.getLogger(__name__)


def initialize_storage_backend(
    config: WorkflowRuntimeConfig,
    metadata: WorkflowMetadata,
    console: Console,
) -> "StorageBackend":
    """Initialize the SQLite storage backend for the workflow."""
    try:
        config_path = Path(config.paths.constructor_path)
        # Expects: .../workflows/WORKFLOW/agent_config/current.yml
        # parents[1] navigates to the WORKFLOW directory.
        if len(config_path.parents) < 2:
            raise ValueError(
                f"Config path too shallow to derive workflow directory: {config_path} "
                f"(expected .../WORKFLOW/agent_config/file.yml)"
            )
        workflow_dir = config_path.parents[1]

        backend = get_storage_backend(
            workflow_path=str(workflow_dir),
            workflow_name=metadata.agent_name,
            backend_type="sqlite",
        )
        backend.initialize()
        db_path = workflow_dir / "agent_io" / "store" / f"{metadata.agent_name}.db"
        logger.debug("Storage backend: %s", db_path)
        return backend
    except (OSError, ValueError, sqlite3.Error) as e:
        logger.error(
            "Storage backend initialization failed: %s",
            e,
            extra={"workflow_name": metadata.agent_name},
        )
        console.print(f"[red]\u274c Storage backend failed: {e}[/red]")
        raise


def initialize_services(
    metadata: WorkflowMetadata,
    config: WorkflowRuntimeConfig,
    storage_backend: "StorageBackend | None",
    console: Console,
) -> tuple[WorkflowServices, Path]:
    """Initialize all workflow services.

    Returns:
        A ``(services, agent_folder)`` tuple.
    """
    fire_event(WorkflowServicesInitializationStartEvent(workflow_name=metadata.agent_name))

    action_runner = create_action_runner(
        use_tools=config.use_tools,
        storage_backend=storage_backend,
    )
    action_runner.execution_order = metadata.execution_order
    action_runner.action_indices = metadata.action_indices
    action_runner.action_configs = metadata.action_configs
    action_runner.virtual_actions = metadata.virtual_actions
    action_runner.workflow_name = metadata.agent_name
    action_runner.project_root = config.project_root

    workflow_defaults = config.manager.user_config.get("defaults") or {}
    action_runner.data_source_config = workflow_defaults.get("data_source")

    # Build batch components directly (no facade)
    from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
        BatchClientResolver,
    )
    from agent_actions.llm.batch.infrastructure.batch_source_handler import (
        BatchSourceHandler,
    )
    from agent_actions.llm.batch.infrastructure.context import BatchContextManager
    from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager
    from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
    from agent_actions.llm.batch.service import create_registry_manager_factory
    from agent_actions.llm.batch.services.processing import BatchProcessingService

    result_processor = BatchResultStrategy()
    context_manager = BatchContextManager()
    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    source_handler = BatchSourceHandler()
    registry_manager_factory = create_registry_manager_factory()
    job_manager = BatchJobManager(client_resolver=client_resolver)

    processing_service = BatchProcessingService(
        client_resolver=client_resolver,
        context_manager=context_manager,
        result_processor=result_processor,
        registry_manager_factory=registry_manager_factory,
        source_handler=source_handler,
        action_indices=metadata.action_indices,
        dependency_configs=metadata.action_configs,
        storage_backend=storage_backend,
        action_name=metadata.agent_name,
    )

    agent_folder = Path(
        action_runner.get_action_folder(metadata.agent_name, project_root=config.project_root)
    )
    status_file = agent_folder / ".agent_status.json"

    version_correlator = VersionOutputCorrelator(
        agent_folder,
        storage_backend=action_runner.storage_backend,
    )

    state_manager = ActionStateManager(status_file, metadata.execution_order)
    skip_evaluator = SkipEvaluator(console)
    batch_manager = BatchLifecycleManager(
        job_manager, processing_service, console, storage_backend=storage_backend
    )
    output_manager = ActionOutputManager(
        OutputManagerConfig(
            agent_folder=agent_folder,
            execution_order=metadata.execution_order,
            action_configs=metadata.action_configs,
            action_status=state_manager.action_status,
            version_correlator=version_correlator,
            console=console,
            storage_backend=action_runner.storage_backend,
            data_source_config=action_runner.data_source_config,
        )
    )

    action_executor = ActionExecutor(
        ExecutorDependencies(
            action_runner=action_runner,
            state_manager=state_manager,
            skip_evaluator=skip_evaluator,
            batch_manager=batch_manager,
            output_manager=output_manager,
        ),
        console=console,
    )

    action_level_orchestrator = ActionLevelOrchestrator(
        metadata.execution_order, metadata.action_configs, console
    )

    manifest_manager = ManifestManager(agent_folder)

    levels = action_level_orchestrator.compute_execution_levels()
    manifest_manager.initialize_manifest(
        workflow_name=metadata.agent_name,
        execution_order=metadata.execution_order,
        levels=levels,
        action_configs=metadata.action_configs,
    )

    action_runner.manifest_manager = manifest_manager

    services = WorkflowServices(
        core=CoreServices(
            action_runner=action_runner,
            state_manager=state_manager,
            action_executor=action_executor,
            action_level_orchestrator=action_level_orchestrator,
        ),
        support=SupportServices(
            version_correlator=version_correlator,
            skip_evaluator=skip_evaluator,
            batch_manager=batch_manager,
            output_manager=output_manager,
            manifest_manager=manifest_manager,
        ),
    )

    return services, agent_folder
