"""Smoke tests for batch service construction paths.

After removing the BatchService facade, callers construct services directly.
These tests verify that each construction site uses the correct constructor
args and produces a usable service instance.
"""

from unittest.mock import MagicMock

from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.batch.infrastructure.batch_source_handler import BatchSourceHandler
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
from agent_actions.llm.batch.service import create_registry_manager_factory
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.retrieval import BatchRetrievalService
from agent_actions.llm.batch.services.submission import BatchSubmissionService


class TestServiceInitConstruction:
    """Mirrors the construction in workflow/service_init.py."""

    def test_processing_service_and_job_manager_share_client_resolver(self):
        """Critical invariant: job_manager and processing_service share a resolver."""
        client_resolver = BatchClientResolver(client_cache={}, default_client=None)
        context_manager = BatchContextManager()
        registry_manager_factory = create_registry_manager_factory()
        job_manager = BatchJobManager(client_resolver=client_resolver)

        processing_service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=BatchResultProcessor(),
            registry_manager_factory=registry_manager_factory,
            source_handler=BatchSourceHandler(),
            action_indices={"action_a": 0},
            dependency_configs={"action_a": {"kind": "llm"}},
            storage_backend=MagicMock(),
            action_name="test_workflow",
        )

        assert job_manager._client_resolver is processing_service._client_resolver

    def test_batch_lifecycle_manager_construction(self):
        """Verify BatchLifecycleManager accepts the new (job_manager, processing_service) args."""
        from agent_actions.workflow.managers.batch import BatchLifecycleManager

        job_manager = MagicMock(spec=BatchJobManager)
        processing_service = MagicMock(spec=BatchProcessingService)
        storage_backend = MagicMock()

        manager = BatchLifecycleManager(
            job_manager, processing_service, storage_backend=storage_backend
        )
        assert manager.job_manager is job_manager
        assert manager.processing_service is processing_service


class TestPipelineConstruction:
    """Mirrors the construction in workflow/pipeline.py _handle_batch_generation."""

    def test_submission_service_construction_with_indices(self):
        """Pipeline creates a BatchSubmissionService with task_preparator carrying indices."""
        agent_indices = {"extract": 0, "transform": 1}
        task_preparator = BatchTaskPreparator(
            action_indices=agent_indices,
            dependency_configs={"extract": {"kind": "llm"}},
        )
        client_resolver = BatchClientResolver(client_cache={}, default_client=None)
        context_manager = BatchContextManager()
        registry_manager_factory = create_registry_manager_factory()

        service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=registry_manager_factory,
        )
        assert service._task_preparator is task_preparator


class TestBatchCliConstruction:
    """Mirrors the construction in llm/batch/batch_cli.py."""

    def test_submission_service_for_status(self):
        """Status command creates a minimal BatchSubmissionService."""
        service = BatchSubmissionService(
            task_preparator=BatchTaskPreparator(),
            client_resolver=BatchClientResolver(client_cache={}, default_client=None),
            context_manager=BatchContextManager(),
            registry_manager_factory=create_registry_manager_factory(),
        )
        assert service is not None

    def test_retrieval_service_for_retrieve(self):
        """Retrieve command creates a BatchRetrievalService."""
        service = BatchRetrievalService(
            client_resolver=BatchClientResolver(client_cache={}, default_client=None),
            context_manager=BatchContextManager(),
            registry_manager_factory=create_registry_manager_factory(),
        )
        assert service is not None


class TestInitialPipelineConstruction:
    """Mirrors the construction in input/preprocessing/staging/initial_pipeline.py."""

    def test_submission_service_no_arg_preparator(self):
        """Initial pipeline creates BatchSubmissionService with default BatchTaskPreparator."""
        service = BatchSubmissionService(
            task_preparator=BatchTaskPreparator(),
            client_resolver=BatchClientResolver(client_cache={}, default_client=None),
            context_manager=BatchContextManager(),
            registry_manager_factory=create_registry_manager_factory(),
        )
        assert service is not None
