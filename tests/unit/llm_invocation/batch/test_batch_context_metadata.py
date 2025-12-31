"""Tests for BatchContextMetadata helper class.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of the context metadata helper.
"""

import pytest
from typing import Dict, Any


class TestSetFilterStatus:
    """Tests for set_filter_status method."""

    def test_set_filter_status_included(self):
        """Should set filter status to included."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )
        from agent_actions.llm_invocation.batch.batch_constants import FilterStatus

        record: Dict[str, Any] = {"id": "test"}
        BatchContextMetadata.set_filter_status(record, FilterStatus.INCLUDED)

        assert record.get("_batch_filter_status") == "included"

    def test_set_filter_status_skipped(self):
        """Should set filter status to skipped."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )
        from agent_actions.llm_invocation.batch.batch_constants import FilterStatus

        record: Dict[str, Any] = {"id": "test"}
        BatchContextMetadata.set_filter_status(record, FilterStatus.SKIPPED)

        assert record.get("_batch_filter_status") == "skipped"

    def test_set_filter_status_filtered(self):
        """Should set filter status to filtered."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )
        from agent_actions.llm_invocation.batch.batch_constants import FilterStatus

        record: Dict[str, Any] = {"id": "test"}
        BatchContextMetadata.set_filter_status(record, FilterStatus.FILTERED)

        assert record.get("_batch_filter_status") == "filtered"


class TestGetFilterStatus:
    """Tests for get_filter_status method."""

    def test_get_filter_status_returns_status(self):
        """Should return the filter status when present."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )
        from agent_actions.llm_invocation.batch.batch_constants import FilterStatus

        record = {"id": "test", "_batch_filter_status": "included"}
        status = BatchContextMetadata.get_filter_status(record)

        assert status == FilterStatus.INCLUDED

    def test_get_filter_status_returns_none_when_missing(self):
        """Should return None when no filter status is set."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test"}
        status = BatchContextMetadata.get_filter_status(record)

        assert status is None

    def test_get_filter_status_handles_unknown_status(self):
        """Should return None for unknown status values."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "unknown"}
        status = BatchContextMetadata.get_filter_status(record)

        assert status is None


class TestFilterStatusCheckers:
    """Tests for is_included, is_skipped, is_filtered methods."""

    def test_is_included_true(self):
        """Should return True when status is included."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "included"}
        assert BatchContextMetadata.is_included(record) is True

    def test_is_included_false(self):
        """Should return False when status is not included."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "skipped"}
        assert BatchContextMetadata.is_included(record) is False

    def test_is_included_false_when_missing(self):
        """Should return False when no status is set."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test"}
        assert BatchContextMetadata.is_included(record) is False

    def test_is_skipped_true(self):
        """Should return True when status is skipped."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "skipped"}
        assert BatchContextMetadata.is_skipped(record) is True

    def test_is_skipped_false(self):
        """Should return False when status is not skipped."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "included"}
        assert BatchContextMetadata.is_skipped(record) is False

    def test_is_filtered_true(self):
        """Should return True when status is filtered."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "filtered"}
        assert BatchContextMetadata.is_filtered(record) is True

    def test_is_filtered_false(self):
        """Should return False when status is not filtered."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "included"}
        assert BatchContextMetadata.is_filtered(record) is False


class TestPassthroughFields:
    """Tests for passthrough fields methods."""

    def test_set_passthrough_fields(self):
        """Should set passthrough fields on record."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record: Dict[str, Any] = {"id": "test"}
        passthrough = {"original_id": "123", "source": "input"}
        BatchContextMetadata.set_passthrough_fields(record, passthrough)

        assert record.get("_passthrough_fields") == passthrough

    def test_get_passthrough_fields_returns_fields(self):
        """Should return passthrough fields when present."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        passthrough = {"original_id": "123"}
        record = {"id": "test", "_passthrough_fields": passthrough}
        result = BatchContextMetadata.get_passthrough_fields(record)

        assert result == passthrough

    def test_get_passthrough_fields_returns_empty_when_missing(self):
        """Should return empty dict when no passthrough fields."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test"}
        result = BatchContextMetadata.get_passthrough_fields(record)

        assert result == {}

    def test_pop_passthrough_fields_removes_and_returns(self):
        """Should remove and return passthrough fields."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        passthrough = {"original_id": "123"}
        record: Dict[str, Any] = {"id": "test", "_passthrough_fields": passthrough}
        result = BatchContextMetadata.pop_passthrough_fields(record)

        assert result == passthrough
        assert "_passthrough_fields" not in record

    def test_pop_passthrough_fields_returns_empty_when_missing(self):
        """Should return empty dict when no passthrough fields to pop."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record: Dict[str, Any] = {"id": "test"}
        result = BatchContextMetadata.pop_passthrough_fields(record)

        assert result == {}


class TestRetryMetadata:
    """Tests for retry metadata methods."""

    def test_set_retry_metadata(self):
        """Should set retry metadata on record."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record: Dict[str, Any] = {"id": "test"}
        metadata = {"attempt": 1, "original_batch_id": "batch_123"}
        BatchContextMetadata.set_retry_metadata(record, metadata)

        assert record.get("_retry_metadata") == metadata

    def test_get_retry_metadata_returns_metadata(self):
        """Should return retry metadata when present."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        metadata = {"attempt": 1}
        record = {"id": "test", "_retry_metadata": metadata}
        result = BatchContextMetadata.get_retry_metadata(record)

        assert result == metadata

    def test_get_retry_metadata_returns_empty_when_missing(self):
        """Should return empty dict when no retry metadata."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test"}
        result = BatchContextMetadata.get_retry_metadata(record)

        assert result == {}


class TestStripInternalFields:
    """Tests for strip_internal_fields method."""

    def test_strip_all_internal_fields(self):
        """Should remove all internal metadata fields."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record: Dict[str, Any] = {
            "id": "test",
            "content": "data",
            "_batch_filter_status": "included",
            "_passthrough_fields": {"key": "value"},
            "_retry_metadata": {"attempt": 1},
        }

        result = BatchContextMetadata.strip_internal_fields(record)

        assert result == {"id": "test", "content": "data"}

    def test_strip_preserves_non_internal_fields(self):
        """Should preserve regular fields."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "content": "data", "custom_field": 123}

        result = BatchContextMetadata.strip_internal_fields(record)

        assert result == {"id": "test", "content": "data", "custom_field": 123}

    def test_strip_returns_new_dict(self):
        """Should return a new dict, not modify in place."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "included"}
        original_record = record.copy()

        result = BatchContextMetadata.strip_internal_fields(record)

        # Original should be unchanged
        assert record == original_record
        # Result should be different object
        assert result is not record

    def test_strip_handles_empty_record(self):
        """Should handle empty record gracefully."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record: Dict[str, Any] = {}
        result = BatchContextMetadata.strip_internal_fields(record)

        assert result == {}


class TestHasInternalFields:
    """Tests for has_internal_fields method."""

    def test_has_internal_fields_true(self):
        """Should return True when internal fields present."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "_batch_filter_status": "included"}
        assert BatchContextMetadata.has_internal_fields(record) is True

    def test_has_internal_fields_false(self):
        """Should return False when no internal fields."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record = {"id": "test", "content": "data"}
        assert BatchContextMetadata.has_internal_fields(record) is False

    def test_has_internal_fields_empty(self):
        """Should return False for empty record."""
        from agent_actions.llm_invocation.batch.batch_context_metadata import (
            BatchContextMetadata,
        )

        record: Dict[str, Any] = {}
        assert BatchContextMetadata.has_internal_fields(record) is False
