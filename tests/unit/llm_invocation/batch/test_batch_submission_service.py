"""Tests for BatchSubmissionService.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of the submission service.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class TestBatchSubmissionServiceInit:
    """Tests for BatchSubmissionService initialization."""

    def test_init_with_all_dependencies(self):
        """Should initialize with all required dependencies."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )

        task_preparator = MagicMock()
        client_resolver = MagicMock()
        context_manager = MagicMock()
        registry_manager_factory = MagicMock()

        service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=registry_manager_factory,
        )

        assert service._task_preparator is task_preparator
        assert service._client_resolver is client_resolver
        assert service._context_manager is context_manager

    def test_init_with_force_batch_flag(self):
        """Should accept force_batch flag."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )

        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(),
            force_batch=True,
        )

        assert service._force_batch is True


class TestPrepareTasksBatch:
    """Tests for prepare_batch_tasks method."""

    def test_prepares_tasks_with_provider(self):
        """Should prepare tasks using task preparator."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )

        # Setup mock preparator
        prepared = MagicMock()
        prepared.tasks = [{"id": "1"}, {"id": "2"}]
        prepared.context_map = {"record_1": {}}
        prepared.task_count = 2
        prepared.stats.filtered_items = 0
        prepared.stats.skipped_items = 0

        task_preparator = MagicMock()
        task_preparator.prepare_tasks.return_value = prepared

        client_resolver = MagicMock()
        provider = MagicMock()
        client_resolver.get_for_config.return_value = provider

        service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        tasks, context_map = service.prepare_batch_tasks(
            agent_config={"model_vendor": "openai"},
            data=[{"text": "hello"}],
        )

        assert tasks == [{"id": "1"}, {"id": "2"}]
        assert context_map == {"record_1": {}}
        task_preparator.prepare_tasks.assert_called_once()


class TestCheckStatus:
    """Tests for check_status method."""

    def test_returns_status_from_provider(self):
        """Should return status from provider."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )
        from agent_actions.llm_invocation.batch.batch_constants import BatchStatus

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        status = service.check_status("batch_123", "/tmp/output")

        assert status == BatchStatus.COMPLETED

    def test_raises_external_error_on_failure(self):
        """Should raise ExternalServiceError when check fails."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )
        from agent_actions.errors import ExternalServiceError

        manager = MagicMock()
        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.side_effect = Exception("API error")

        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        with pytest.raises(ExternalServiceError):
            service.check_status("batch_123", "/tmp/output")


class TestSubmitBatchJob:
    """Tests for submit_batch_job method."""

    def test_returns_existing_batch_id_if_in_flight(self):
        """Should return existing batch ID if in-flight batch exists."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )

        entry = MagicMock()
        entry.is_in_flight = True
        entry.batch_id = "existing_batch"

        manager = MagicMock()
        manager.get_batch_job.return_value = entry

        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
            force_batch=False,
        )

        result = service.submit_batch_job(
            agent_config={"model_vendor": "openai"},
            batch_name="test_batch",
            data=[{"text": "hello"}],
            output_directory="/tmp/output",
        )

        assert result == "existing_batch"

    def test_force_bypasses_in_flight_check(self):
        """Should submit new batch when force=True even if in-flight exists."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )

        # Setup existing in-flight batch
        entry = MagicMock()
        entry.is_in_flight = True
        entry.batch_id = "existing_batch"

        manager = MagicMock()
        manager.get_batch_job.return_value = entry

        # Setup task preparation
        prepared = MagicMock()
        prepared.tasks = [{"id": "1"}]
        prepared.context_map = {}
        prepared.task_count = 1
        prepared.stats.filtered_items = 0
        prepared.stats.skipped_items = 0

        task_preparator = MagicMock()
        task_preparator.prepare_tasks.return_value = prepared

        # Setup provider
        provider = MagicMock()
        provider.submit_batch.return_value = ("new_batch_123", "submitted")

        client_resolver = MagicMock()
        client_resolver.get_for_config.return_value = provider

        service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
            force_batch=False,
        )

        result = service.submit_batch_job(
            agent_config={"model_vendor": "openai"},
            batch_name="test_batch",
            data=[{"text": "hello"}],
            output_directory="/tmp/output",
            force=True,
        )

        assert result == "new_batch_123"

    def test_returns_passthrough_when_no_tasks(self):
        """Should return passthrough dict when no tasks after filtering."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )

        # Setup empty task preparation
        prepared = MagicMock()
        prepared.tasks = []
        prepared.context_map = {}
        prepared.task_count = 0
        prepared.stats.filtered_items = 2
        prepared.stats.skipped_items = 0

        task_preparator = MagicMock()
        task_preparator.prepare_tasks.return_value = prepared

        client_resolver = MagicMock()

        manager = MagicMock()
        manager.get_batch_job.return_value = None

        service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result = service.submit_batch_job(
            agent_config={"model_vendor": "openai"},
            batch_name="test_batch",
            data=[{"text": "hello"}],
            output_directory="/tmp/output",
        )

        assert result["type"] == "passthrough"

    def test_submits_batch_and_saves_to_registry(self):
        """Should submit batch and save entry to registry."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )

        # Setup task preparation
        prepared = MagicMock()
        prepared.tasks = [{"id": "1"}]
        prepared.context_map = {"record_1": {}}
        prepared.task_count = 1
        prepared.stats.filtered_items = 0
        prepared.stats.skipped_items = 0

        task_preparator = MagicMock()
        task_preparator.prepare_tasks.return_value = prepared

        # Setup provider
        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_123", "submitted")

        client_resolver = MagicMock()
        client_resolver.get_for_config.return_value = provider

        # Setup manager
        manager = MagicMock()
        manager.get_batch_job.return_value = None

        context_manager = MagicMock()

        service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result = service.submit_batch_job(
            agent_config={"model_vendor": "openai"},
            batch_name="test_batch",
            data=[{"text": "hello"}],
            output_directory="/tmp/output",
        )

        assert result == "batch_123"
        manager.save_batch_job.assert_called_once()
        context_manager.save_batch_context_map.assert_called_once()

    def test_raises_config_error_when_no_vendor(self):
        """Should raise ConfigValidationError when model_vendor missing."""
        from agent_actions.llm_invocation.batch.batch_submission_service import (
            BatchSubmissionService,
        )
        from agent_actions.errors import ConfigValidationError

        prepared = MagicMock()
        prepared.tasks = [{"id": "1"}]
        prepared.context_map = {}
        prepared.task_count = 1
        prepared.stats.filtered_items = 0
        prepared.stats.skipped_items = 0

        task_preparator = MagicMock()
        task_preparator.prepare_tasks.return_value = prepared

        manager = MagicMock()
        manager.get_batch_job.return_value = None

        service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        with pytest.raises(ConfigValidationError):
            service.submit_batch_job(
                agent_config={},  # No model_vendor
                batch_name="test_batch",
                data=[{"text": "hello"}],
                output_directory="/tmp/output",
            )
