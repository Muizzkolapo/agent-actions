"""Tests for BatchContextMetadata helper class.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of the context metadata helper.
"""

import pytest
from typing import Any, Dict


class TestSetFilterStatus:
    """Tests for set_filter_status method."""

    @pytest.mark.parametrize(
        "status_name,expected_value",
        [
            ("INCLUDED", "included"),
            ("SKIPPED", "skipped"),
            ("FILTERED", "filtered"),
        ],
    )
    def test_set_filter_status(self, status_name, expected_value):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
        from agent_actions.llm.batch.core.batch_constants import FilterStatus

        record: Dict[str, Any] = {"id": "test"}
        BatchContextMetadata.set_filter_status(record, getattr(FilterStatus, status_name))

        assert record.get("_batch_filter_status") == expected_value


class TestGetFilterStatus:
    """Tests for get_filter_status method."""

    def test_get_filter_status_returns_status(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
        from agent_actions.llm.batch.core.batch_constants import FilterStatus

        record = {"id": "test", "_batch_filter_status": "included"}
        assert BatchContextMetadata.get_filter_status(record) == FilterStatus.INCLUDED

    @pytest.mark.parametrize(
        "record",
        [
            pytest.param({"id": "test"}, id="missing"),
            pytest.param({"id": "test", "_batch_filter_status": "unknown"}, id="unknown"),
        ],
    )
    def test_get_filter_status_returns_none(self, record):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        assert BatchContextMetadata.get_filter_status(record) is None


class TestFilterStatusCheckers:
    """Tests for is_included, is_skipped, is_filtered methods."""

    @pytest.mark.parametrize(
        "method,status_value,expected",
        [
            ("is_included", "included", True),
            ("is_included", "skipped", False),
            ("is_included", None, False),
            ("is_skipped", "skipped", True),
            ("is_skipped", "included", False),
            ("is_filtered", "filtered", True),
            ("is_filtered", "included", False),
        ],
        ids=[
            "included-true",
            "included-false",
            "included-missing",
            "skipped-true",
            "skipped-false",
            "filtered-true",
            "filtered-false",
        ],
    )
    def test_status_checker(self, method, status_value, expected):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        record: Dict[str, Any] = {"id": "test"}
        if status_value is not None:
            record["_batch_filter_status"] = status_value

        assert getattr(BatchContextMetadata, method)(record) is expected


class TestPassthroughFields:
    """Tests for passthrough fields methods."""

    def test_set_passthrough_fields(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        record: Dict[str, Any] = {"id": "test"}
        passthrough = {"original_id": "123", "source": "input"}
        BatchContextMetadata.set_passthrough_fields(record, passthrough)

        assert record.get("_passthrough_fields") == passthrough

    def test_get_passthrough_fields_returns_fields(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        passthrough = {"original_id": "123"}
        record = {"id": "test", "_passthrough_fields": passthrough}
        assert BatchContextMetadata.get_passthrough_fields(record) == passthrough

    def test_get_passthrough_fields_returns_empty_when_missing(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        assert BatchContextMetadata.get_passthrough_fields({"id": "test"}) == {}

    def test_pop_passthrough_fields_removes_and_returns(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        passthrough = {"original_id": "123"}
        record: Dict[str, Any] = {"id": "test", "_passthrough_fields": passthrough}
        result = BatchContextMetadata.pop_passthrough_fields(record)

        assert result == passthrough
        assert "_passthrough_fields" not in record

    def test_pop_passthrough_fields_returns_empty_when_missing(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        assert BatchContextMetadata.pop_passthrough_fields({"id": "test"}) == {}


class TestStripInternalFields:
    """Tests for strip_internal_fields method."""

    def test_strip_all_internal_fields(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        record: Dict[str, Any] = {
            "id": "test",
            "content": "data",
            "_batch_filter_status": "included",
            "_passthrough_fields": {"key": "value"},
        }
        assert BatchContextMetadata.strip_internal_fields(record) == {
            "id": "test",
            "content": "data",
        }

    def test_strip_preserves_non_internal_fields(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        record = {"id": "test", "content": "data", "custom_field": 123}
        assert BatchContextMetadata.strip_internal_fields(record) == record

    def test_strip_returns_new_dict(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        record = {"id": "test", "_batch_filter_status": "included"}
        original_record = record.copy()
        result = BatchContextMetadata.strip_internal_fields(record)

        assert record == original_record
        assert result is not record

    def test_strip_handles_empty_record(self):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        assert BatchContextMetadata.strip_internal_fields({}) == {}


class TestHasInternalFields:
    """Tests for has_internal_fields method."""

    @pytest.mark.parametrize(
        "record,expected",
        [
            pytest.param({"id": "test", "_batch_filter_status": "included"}, True, id="present"),
            pytest.param({"id": "test", "content": "data"}, False, id="absent"),
            pytest.param({}, False, id="empty"),
        ],
    )
    def test_has_internal_fields(self, record, expected):
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

        assert BatchContextMetadata.has_internal_fields(record) is expected
