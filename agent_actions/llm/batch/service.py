"""Batch processing service facade delegating to specialized services."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from agent_actions.llm.batch.infrastructure.batch_data_loader import BatchDataLoader

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.config.di.container import registry
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
from agent_actions.llm.providers.batch_base import BaseBatchClient

logger = logging.getLogger(__name__)


def _create_registry_manager_factory() -> Callable[[str], BatchRegistryManager]:
    """Create a factory that creates/caches registry managers."""
    _cache: dict[str, BatchRegistryManager] = {}

    def get_registry_manager(output_directory: str) -> BatchRegistryManager:
        if output_directory not in _cache:
            _cache[output_directory] = BatchRegistryManager(
                Path(output_directory) / "batch" / ".batch_registry.json"
            )
        return _cache[output_directory]

    return get_registry_manager


@registry.register_service("batch_service")
class BatchService:
    """Thin facade for batch processing that delegates to specialized services."""

    def __init__(
        self,
        # Pre-built services (for testing/dependency injection)
        submission_service: Any | None = None,
        retrieval_service: Any | None = None,
        processing_service: Any | None = None,
        # Legacy params for backward compatibility
        provider: BaseBatchClient | None = None,
        agent_indices: dict[str, int] | None = None,
        dependency_configs: dict[str, dict] | None = None,
        force_batch: bool = False,
        task_preparator: BatchTaskPreparator | None = None,
        result_processor: BatchResultProcessor | None = None,
        context_manager: BatchContextManager | None = None,
        client_resolver: BatchClientResolver | None = None,
        job_manager: Any | None = None,  # BatchJobManager, uses Any to avoid circular import
        source_handler: Any | None = None,  # BatchSourceHandler
        storage_backend: Optional["StorageBackend"] = None,
        action_name: str | None = None,
    ):
        """Initialize batch service facade with optional pre-built services."""
        from agent_actions.llm.batch.infrastructure.batch_source_handler import (
            BatchSourceHandler,
        )
        from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager

        # Store pre-built services
        self._submission_service = submission_service
        self._retrieval_service = retrieval_service
        self._processing_service = processing_service

        # Store legacy init params for lazy service initialization
        self.data_loader = BatchDataLoader()
        self.provider = provider
        self.force_batch = force_batch
        self._provider_cache: dict[str, Any] = {}
        self.agent_indices = agent_indices or {}
        self.dependency_configs = dependency_configs or {}

        # Shared components (used by multiple services)
        self._task_preparator = task_preparator or BatchTaskPreparator(
            agent_indices=agent_indices,
            dependency_configs=dependency_configs,
            storage_backend=storage_backend,
        )
        self._result_processor = result_processor or BatchResultProcessor()
        self._context_manager = context_manager or BatchContextManager()
        self._client_resolver = client_resolver or BatchClientResolver(
            client_cache=self._provider_cache, default_client=self.provider
        )
        self._source_handler = source_handler or BatchSourceHandler()
        self._storage_backend = storage_backend
        self._action_name = action_name

        # Registry manager factory (shared across services)
        self._registry_manager_factory = _create_registry_manager_factory()
        self._registry_manager: BatchRegistryManager | None = None

        # Job manager (special case - still used directly for status queries)
        self._job_manager = job_manager or BatchJobManager(client_resolver=self._client_resolver)

    def _get_registry_manager(self, output_directory: str) -> BatchRegistryManager:
        """Get or create registry manager for output directory."""
        if self._registry_manager is None and output_directory:
            self._registry_manager = self._registry_manager_factory(output_directory)
            # Share registry manager with job manager
            self._job_manager.set_registry_manager(self._registry_manager)
        return self._registry_manager

    def _get_submission_service(self):
        """Lazy-initialize submission service."""
        if self._submission_service is None:
            from agent_actions.llm.batch.services.submission import (
                BatchSubmissionService,
            )

            self._submission_service = BatchSubmissionService(
                task_preparator=self._task_preparator,
                client_resolver=self._client_resolver,
                context_manager=self._context_manager,
                registry_manager_factory=self._registry_manager_factory,
                force_batch=self.force_batch,
            )
        return self._submission_service

    def _get_retrieval_service(self):
        """Lazy-initialize retrieval service."""
        if self._retrieval_service is None:
            from agent_actions.llm.batch.services.retrieval import (
                BatchRetrievalService,
            )

            self._retrieval_service = BatchRetrievalService(
                client_resolver=self._client_resolver,
                context_manager=self._context_manager,
                registry_manager_factory=self._registry_manager_factory,
            )
        return self._retrieval_service

    def _get_processing_service(self):
        """Lazy-initialize processing service."""
        if self._processing_service is None:
            from agent_actions.llm.batch.services.processing import (
                BatchProcessingService,
            )

            self._processing_service = BatchProcessingService(
                client_resolver=self._client_resolver,
                context_manager=self._context_manager,
                result_processor=self._result_processor,
                registry_manager_factory=self._registry_manager_factory,
                source_handler=self._source_handler,
                agent_indices=self.agent_indices,
                dependency_configs=self.dependency_configs,
                storage_backend=self._storage_backend,
                action_name=self._action_name,
            )
        return self._processing_service

    # =========================================================================
    # Delegation methods - one-liner delegations to focused services
    # =========================================================================

    def prepare_batch_tasks(
        self, agent_config, data, output_directory=None, batch_name=None, workflow_metadata=None
    ):
        """Prepare batch tasks from data (delegates to submission service)."""
        return self._get_submission_service().prepare_batch_tasks(
            agent_config, data, output_directory, batch_name, workflow_metadata=workflow_metadata
        )

    def submit_batch_job(
        self,
        agent_config,
        batch_name,
        data,
        output_directory=None,
        force=False,
        source_data: Any | None = None,
        workflow_metadata: dict[str, Any] | None = None,
    ):
        """Submit a batch job for processing (delegates to submission service)."""
        return self._get_submission_service().submit_batch_job(
            agent_config,
            batch_name,
            data,
            output_directory,
            force,
            source_data,
            workflow_metadata=workflow_metadata,
        )

    def check_status(self, batch_id: str, output_directory: str = None) -> BatchStatus:
        """Check the status of a batch job (delegates to submission service)."""
        return self._get_submission_service().check_status(batch_id, output_directory)

    def retrieve_results(self, batch_id: str, output_dir: str, file_path: str = None) -> Path:
        """Retrieve and save results from a completed batch job (delegates to retrieval service)."""
        return self._get_retrieval_service().retrieve_results(batch_id, output_dir, file_path)

    def process_batch_results(
        self,
        batch_id: str,
        output_directory: str,
        base_directory: str,
        file_path: str,
        agent_config: dict[str, Any] | None = None,
    ) -> str:
        """Process batch results to workflow output (delegates to processing service)."""
        return self._get_processing_service().process_batch_results(
            batch_id, output_directory, base_directory, file_path, agent_config
        )

    def process_all_batch_results(
        self,
        output_directory: str,
        agent_config: dict[str, Any] | None = None,
        action_name: str | None = None,
    ) -> list[str]:
        """Process all completed batch jobs (delegates to processing service)."""
        return self._get_processing_service().process_all_batch_results(
            output_directory, agent_config, action_name=action_name
        )

    # =========================================================================
    # Job manager methods (still used directly for status queries)
    # =========================================================================

    def are_all_batch_jobs_completed(self, output_directory: str) -> bool:
        """Check if all batch jobs in the registry are completed (delegates to BatchJobManager)."""
        return self._job_manager.are_all_jobs_completed(output_directory)

    def get_batch_registry_status(self, output_directory: str) -> str:
        """Get overall status of all batch jobs in the registry."""
        return self._job_manager.get_registry_status(output_directory)
