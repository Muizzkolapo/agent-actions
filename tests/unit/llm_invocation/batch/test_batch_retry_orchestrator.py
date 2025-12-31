"""Unit tests for batch retry orchestrator."""

import pytest
from unittest.mock import MagicMock, patch
from agent_actions.llm_invocation.batch.retry.batch_retry_orchestrator import (
    RetryMetadata,
    RetryBatchResult,
    RetryChainResult,
    BatchRetryOrchestrator,
)
from agent_actions.llm_invocation.batch.retry.batch_retry_config import RetryConfig
from agent_actions.llm_invocation.batch.processing.batch_result_reconciler import (
    BatchReconciliationResult,
)


class TestRetryMetadata:
    """Tests for RetryMetadata dataclass."""

    def test_default_values(self):
        """Test default metadata values."""
        metadata = RetryMetadata()
        assert metadata.was_retried is False
        assert metadata.retry_attempts == 0
        assert metadata.original_batch_id is None
        assert metadata.final_batch_id is None

    def test_to_dict(self):
        """Test serialization to dictionary."""
        metadata = RetryMetadata(
            was_retried=True,
            retry_attempts=2,
            original_batch_id="batch_001",
            final_batch_id="batch_001_r2",
        )
        result = metadata.to_dict()

        assert result["was_retried"] is True
        assert result["retry_attempts"] == 2
        assert result["original_batch_id"] == "batch_001"
        assert result["final_batch_id"] == "batch_001_r2"


class TestRetryBatchResult:
    """Tests for RetryBatchResult dataclass."""

    def test_all_succeeded_true(self):
        """Test all_succeeded when no missing IDs."""
        result = RetryBatchResult(
            batch_id="batch_r1",
            retry_attempt=1,
            submitted_count=3,
            success_ids={"id1", "id2", "id3"},
            missing_ids=set(),
        )
        assert result.all_succeeded is True

    def test_all_succeeded_false(self):
        """Test all_succeeded when some missing."""
        result = RetryBatchResult(
            batch_id="batch_r1",
            retry_attempt=1,
            submitted_count=3,
            success_ids={"id1", "id2"},
            missing_ids={"id3"},
        )
        assert result.all_succeeded is False


class TestRetryChainResult:
    """Tests for RetryChainResult dataclass."""

    def test_all_succeeded_true(self):
        """Test all_succeeded when no final missing."""
        result = RetryChainResult(
            original_batch_id="batch_001",
            total_attempts=2,
            final_success_count=100,
            final_missing_count=0,
        )
        assert result.all_succeeded is True

    def test_all_succeeded_false(self):
        """Test all_succeeded when some still missing."""
        result = RetryChainResult(
            original_batch_id="batch_001",
            total_attempts=3,
            final_success_count=99,
            final_missing_count=1,
        )
        assert result.all_succeeded is False


class TestBatchRetryOrchestratorShouldRetry:
    """Tests for BatchRetryOrchestrator.should_retry method."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with mocked dependencies."""
        return BatchRetryOrchestrator(
            registry_manager=MagicMock(),
            client_resolver=MagicMock(),
            task_preparator=MagicMock(),
            context_manager=MagicMock(),
        )

    def test_should_retry_with_missing_ids(self, orchestrator):
        """Test retry triggered when missing IDs exist."""
        missing_ids = {"id1", "id2", "id3"}
        config = RetryConfig(enabled=True, max_attempts=3)

        assert orchestrator.should_retry(missing_ids, 0, config) is True
        assert orchestrator.should_retry(missing_ids, 1, config) is True
        assert orchestrator.should_retry(missing_ids, 2, config) is True

    def test_should_not_retry_at_max_attempts(self, orchestrator):
        """Test no retry when max attempts reached."""
        missing_ids = {"id1", "id2"}
        config = RetryConfig(enabled=True, max_attempts=3)

        assert orchestrator.should_retry(missing_ids, 3, config) is False
        assert orchestrator.should_retry(missing_ids, 4, config) is False

    def test_should_not_retry_no_missing_ids(self, orchestrator):
        """Test no retry when no missing IDs."""
        config = RetryConfig(enabled=True, max_attempts=3)

        assert orchestrator.should_retry(set(), 0, config) is False

    def test_should_not_retry_when_disabled(self, orchestrator):
        """Test no retry when config is disabled."""
        missing_ids = {"id1", "id2"}
        config = RetryConfig.disabled()

        assert orchestrator.should_retry(missing_ids, 0, config) is False


class TestBatchRetryOrchestratorGetRetryRecords:
    """Tests for BatchRetryOrchestrator.get_retry_records method."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with mocked dependencies."""
        return BatchRetryOrchestrator(
            registry_manager=MagicMock(),
            client_resolver=MagicMock(),
            task_preparator=MagicMock(),
            context_manager=MagicMock(),
        )

    def test_get_retry_records_filters_correctly(self, orchestrator):
        """Test only missing IDs are returned."""
        context_map = {
            "id1": {"content": "data1", "_batch_filter_status": "included"},
            "id2": {"content": "data2", "_batch_filter_status": "included"},
            "id3": {"content": "data3", "_batch_filter_status": "included"},
        }
        missing_ids = {"id1", "id3"}

        result = orchestrator.get_retry_records(missing_ids, context_map)

        assert "id1" in result
        assert "id3" in result
        assert "id2" not in result

    def test_get_retry_records_copies_data(self, orchestrator):
        """Test records are copied not referenced."""
        context_map = {
            "id1": {"content": "data1"},
        }
        missing_ids = {"id1"}

        result = orchestrator.get_retry_records(missing_ids, context_map)

        # Modify result should not affect original
        result["id1"]["content"] = "modified"
        assert context_map["id1"]["content"] == "data1"

    def test_get_retry_records_missing_id_skipped(self, orchestrator):
        """Test IDs not in context_map are skipped."""
        context_map = {
            "id1": {"content": "data1"},
        }
        missing_ids = {"id1", "id_not_in_map"}

        result = orchestrator.get_retry_records(missing_ids, context_map)

        assert "id1" in result
        assert "id_not_in_map" not in result


class TestBatchRetryOrchestratorAddMetadata:
    """Tests for add_retry_metadata_to_record method."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with mocked dependencies."""
        return BatchRetryOrchestrator(
            registry_manager=MagicMock(),
            client_resolver=MagicMock(),
            task_preparator=MagicMock(),
            context_manager=MagicMock(),
        )

    def test_add_retry_metadata_to_record(self, orchestrator):
        """Test metadata is added correctly."""
        record = {"content": "test", "source_guid": "guid1"}

        result = orchestrator.add_retry_metadata_to_record(
            record=record,
            original_batch_id="batch_001",
            final_batch_id="batch_001_r2",
            retry_attempts=2,
        )

        assert "_retry_metadata" in result
        assert result["_retry_metadata"]["was_retried"] is True
        assert result["_retry_metadata"]["retry_attempts"] == 2
        assert result["_retry_metadata"]["original_batch_id"] == "batch_001"
        assert result["_retry_metadata"]["final_batch_id"] == "batch_001_r2"

    def test_add_retry_metadata_no_retry(self, orchestrator):
        """Test metadata for non-retried record."""
        record = {"content": "test"}

        result = orchestrator.add_retry_metadata_to_record(
            record=record,
            original_batch_id="batch_001",
            final_batch_id="batch_001",
            retry_attempts=0,
        )

        assert result["_retry_metadata"]["was_retried"] is False
        assert result["_retry_metadata"]["retry_attempts"] == 0
