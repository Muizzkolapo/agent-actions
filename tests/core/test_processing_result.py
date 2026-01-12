"""Tests for ProcessingResult dataclass and factory methods."""

import pytest

from agent_actions.core.types import ProcessingResult, ProcessingStatus, RetryState


class TestProcessingResultFactories:
    """Test factory methods for ProcessingResult."""

    def test_success_creates_result_with_success_status(self):
        """ProcessingResult.success() sets status=SUCCESS and executed=True."""
        result = ProcessingResult.success(data=[{"key": "value"}])

        assert result.status == ProcessingStatus.SUCCESS
        assert result.executed is True

    def test_success_accepts_data_list(self):
        """ProcessingResult.success() stores data list correctly."""
        data = [{"key": "value1"}, {"key": "value2"}]
        result = ProcessingResult.success(data=data)

        assert result.data == data

    def test_success_accepts_kwargs(self):
        """ProcessingResult.success() passes through source_guid, node_id, etc."""
        result = ProcessingResult.success(
            data=[{"key": "value"}],
            source_guid="guid-123",
            node_id="node-456",
            passthrough_fields={"field": "value"},
        )

        assert result.source_guid == "guid-123"
        assert result.node_id == "node-456"
        assert result.passthrough_fields == {"field": "value"}

    def test_skipped_creates_result_with_skipped_status(self):
        """ProcessingResult.skipped() sets status=SKIPPED and executed=False."""
        result = ProcessingResult.skipped(passthrough_data={"content": "data"}, reason="guard_skip")

        assert result.status == ProcessingStatus.SKIPPED
        assert result.executed is False
        assert result.skip_reason == "guard_skip"

    def test_skipped_wraps_non_list_data_in_list(self):
        """ProcessingResult.skipped() converts single dict to [dict]."""
        result = ProcessingResult.skipped(passthrough_data={"content": "data"}, reason="test")

        assert isinstance(result.data, list)
        assert len(result.data) == 1
        assert result.data[0] == {"content": "data"}

    def test_skipped_preserves_list_data(self):
        """ProcessingResult.skipped() keeps list data as-is."""
        data = [{"item": 1}, {"item": 2}]
        result = ProcessingResult.skipped(passthrough_data=data, reason="test")

        assert result.data == data

    def test_skipped_stores_reason(self):
        """ProcessingResult.skipped() stores skip_reason correctly."""
        result = ProcessingResult.skipped(passthrough_data={}, reason="guard_condition_false")

        assert result.skip_reason == "guard_condition_false"

    def test_filtered_creates_empty_result(self):
        """ProcessingResult.filtered() sets status=FILTERED, data=[], executed=False."""
        result = ProcessingResult.filtered()

        assert result.status == ProcessingStatus.FILTERED
        assert result.data == []
        assert result.executed is False

    def test_failed_creates_result_with_error(self):
        """ProcessingResult.failed() sets status=FAILED and stores error message."""
        result = ProcessingResult.failed(error="LLM invocation failed")

        assert result.status == ProcessingStatus.FAILED
        assert result.error == "LLM invocation failed"
        assert result.executed is False

    def test_failed_accepts_retry_state(self):
        """ProcessingResult.failed() can include RetryState."""
        retry = RetryState(attempts=3, last_error="Timeout", exhausted=True)
        result = ProcessingResult.failed(error="Max retries exceeded", retry_state=retry)

        assert result.retry_state == retry
        assert result.retry_state.exhausted is True


class TestProcessingResultDefaults:
    """Test default values for ProcessingResult fields."""

    def test_default_data_is_empty_list(self):
        """Default data field is empty list, not None."""
        result = ProcessingResult(status=ProcessingStatus.SUCCESS)

        assert result.data == []
        assert isinstance(result.data, list)

    def test_default_passthrough_fields_is_empty_dict(self):
        """Default passthrough_fields is empty dict."""
        result = ProcessingResult(status=ProcessingStatus.SUCCESS)

        assert result.passthrough_fields == {}
        assert isinstance(result.passthrough_fields, dict)

    def test_default_retry_state_is_fresh(self):
        """Default RetryState has attempts=0, exhausted=False."""
        result = ProcessingResult(status=ProcessingStatus.SUCCESS)

        assert result.retry_state.attempts == 0
        assert result.retry_state.last_error is None
        assert result.retry_state.exhausted is False

    def test_default_executed_is_true(self):
        """Default executed is True (most results are executed)."""
        result = ProcessingResult(status=ProcessingStatus.SUCCESS)

        assert result.executed is True


class TestRetryState:
    """Test RetryState dataclass."""

    def test_retry_state_default_values(self):
        """RetryState defaults: attempts=0, last_error=None, exhausted=False."""
        state = RetryState()

        assert state.attempts == 0
        assert state.last_error is None
        assert state.exhausted is False

    def test_retry_state_tracks_attempts(self):
        """RetryState.attempts increments correctly."""
        state = RetryState(attempts=3)

        assert state.attempts == 3

    def test_retry_state_stores_last_error(self):
        """RetryState.last_error captures error message."""
        state = RetryState(last_error="Connection timeout")

        assert state.last_error == "Connection timeout"

    def test_retry_state_exhausted_flag(self):
        """RetryState.exhausted=True when max attempts reached."""
        state = RetryState(attempts=5, exhausted=True)

        assert state.exhausted is True
