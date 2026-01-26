"""
Test source data lookup in batch processing.

This test captures the bug where source_data was matched by array index
instead of source_guid, causing failures when:
- Input records (N) > Source records (M)
- Multiple input records share the same source_guid

Regression test for: Multiple derived records from same source document
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import List, Dict, Any

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.core.batch_models import PreparedBatchTasks


class TestSourceDataLookup:
    """Test source_guid-based lookup (not index-based)."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock batch provider."""
        provider = MagicMock()
        provider.prepare_tasks = MagicMock(side_effect=lambda tasks, config: tasks)
        return provider

    @pytest.fixture
    def agent_config_with_source_template(self):
        """Agent config that references source.page_content."""
        return {
            "name": "test_agent",
            "agent_type": "test_agent",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "json_mode": True,
            "prompt": "Content: {{ source.page_content }}",
            "schema": {"result": "string"},  # Simple schema format
        }

    @pytest.fixture
    def source_data_17_records(self) -> List[Dict[str, Any]]:
        """
        17 source records (simulating original page content).

        Each has unique source_guid and page_content.
        """
        return [
            {
                "source_guid": f"source-guid-{i}",
                "page_content": f"Original page content {i}",
                "url": f"https://example.com/page{i}",
            }
            for i in range(17)
        ]

    @pytest.fixture
    def input_data_61_records(self) -> List[Dict[str, Any]]:
        """
        61 processed records derived from 17 source records.

        Multiple records can share the same source_guid (e.g., extracted QA pairs).
        Distribution:
        - source-guid-0: 3 records (indices 0-2)
        - source-guid-1: 4 records (indices 3-6)
        - source-guid-2: 4 records (indices 7-10)
        - source-guid-3: 5 records (indices 11-15)
        - source-guid-4: 2 records (indices 16-17)
        - source-guid-5 to source-guid-16: 0 records each (indices 18-60 will fail with index lookup)
        """
        records = []
        distribution = [
            (0, 3),  # source-guid-0: 3 records
            (1, 4),  # source-guid-1: 4 records
            (2, 4),  # source-guid-2: 4 records
            (3, 5),  # source-guid-3: 5 records
            (4, 2),  # source-guid-4: 2 records (17 total so far)
            (5, 4),  # source-guid-5: 4 records (would fail with index lookup)
            (6, 3),  # source-guid-6: 3 records
            (7, 4),  # source-guid-7: 4 records
            (8, 4),  # source-guid-8: 4 records
            (9, 5),  # source-guid-9: 5 records
            (10, 2), # source-guid-10: 2 records
            (11, 3), # source-guid-11: 3 records
            (12, 3), # source-guid-12: 3 records
            (13, 4), # source-guid-13: 4 records
            (14, 4), # source-guid-14: 4 records
            (15, 2), # source-guid-15: 2 records
            (16, 5), # source-guid-16: 5 records (61 total)
        ]

        for source_idx, count in distribution:
            source_guid = f"source-guid-{source_idx}"
            for j in range(count):
                records.append({
                    "target_id": f"target-{len(records)}",
                    "source_guid": source_guid,
                    "content": {
                        "question": f"Question {len(records)}",
                        "answer": f"Answer {len(records)}",
                    },
                })

        assert len(records) == 61, "Should have exactly 61 records"
        return records

    def test_source_lookup_by_source_guid_not_index(
        self,
        agent_config_with_source_template,
        source_data_17_records,
        input_data_61_records,
        mock_provider,
    ):
        """
        CRITICAL: Source lookup must use source_guid, not array index.

        This test reproduces the bug where:
        - 17 source records with page_content
        - 61 input records derived from them
        - INDEX-based lookup: Only first 17 succeed (idx 0-16)
        - source_guid-based lookup: All 61 succeed

        The template references {{ source.page_content }}, which should
        be available for ALL 61 records by looking up their source_guid.
        """
        preparator = BatchTaskPreparator()

        # Act: Prepare tasks with source_data
        with patch("agent_actions.llm.batch.processing.preparator.logger"):
            result: PreparedBatchTasks = preparator.prepare_tasks(
                agent_config=agent_config_with_source_template,
                data=input_data_61_records,
                provider=mock_provider,
                output_directory="/tmp/test",
                batch_name="test.json",
                source_data=source_data_17_records,
            )

        # Assert: ALL 61 records should be prepared successfully
        # (With index-based lookup, only 17 would succeed, 44 would fail with template error)
        assert result.stats.total_items == 61, "Should process all 61 input records"
        assert result.stats.included_items == 61, "All 61 should be included (not filtered)"
        assert result.stats.error_items == 0, "No errors should occur"

        assert len(result.tasks) == 61, "Should prepare all 61 tasks"
        assert len(result.context_map) == 61, "Context map should have all 61 records"

    def test_source_lookup_handles_missing_source_guid_gracefully(
        self,
        agent_config_with_source_template,
        source_data_17_records,
        mock_provider,
    ):
        """
        When source_guid is missing or not found, should fail in preflight.

        The template error is caught during preflight validation.
        """
        from agent_actions.errors import TemplateVariableError

        # Input record without source_guid
        input_data = [
            {
                "target_id": "target-1",
                # No source_guid - should fallback to row_content
                "content": {
                    "question": "Question 1",
                },
            }
        ]

        preparator = BatchTaskPreparator()

        # Should raise TemplateVariableError during preflight
        with pytest.raises(TemplateVariableError) as exc_info:
            with patch("agent_actions.llm.batch.processing.preparator.logger"):
                preparator.prepare_tasks(
                    agent_config=agent_config_with_source_template,
                    data=input_data,
                    provider=mock_provider,
                    source_data=source_data_17_records,
                )

        assert "page_content" in str(exc_info.value)

    def test_source_lookup_without_source_data_uses_row_content(
        self,
        mock_provider,
    ):
        """
        When source_data is not provided, should use row_content.

        This is the fallback behavior.
        """
        agent_config = {
            "name": "test_agent",
            "agent_type": "test_agent",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "json_mode": True,
            "prompt": "Content: {{ source.text }}",
            "schema": {"result": "string"},
        }

        input_data = [
            {
                "target_id": "target-1",
                "source_guid": "source-1",
                "content": {
                    "text": "Hello from row content",
                },
            }
        ]

        preparator = BatchTaskPreparator()

        with patch("agent_actions.llm.batch.processing.preparator.logger"):
            result = preparator.prepare_tasks(
                agent_config=agent_config,
                data=input_data,
                provider=mock_provider,
                source_data=None,  # No source data provided
            )

        # Should succeed using row_content as fallback
        assert result.stats.included_items == 1
        assert result.stats.error_items == 0


class TestSourceLookupPreflight:
    """Test that preflight validation also uses source_guid lookup."""

    @pytest.fixture
    def mock_provider(self):
        provider = MagicMock()
        provider.prepare_tasks = MagicMock(side_effect=lambda tasks, config: tasks)
        return provider

    def test_preflight_uses_source_guid_lookup_not_index(
        self,
        mock_provider,
    ):
        """
        Preflight validation should also lookup by source_guid, not index.

        If the first input record's source_guid != source_data[0],
        it should still find the correct source.
        """
        agent_config = {
            "name": "test_agent",
            "agent_type": "test_agent",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "json_mode": True,
            "prompt": "Content: {{ source.page_content }}",
            "schema": {"result": "string"},
        }

        # Source data: source_guid "B" is at index 0
        source_data = [
            {"source_guid": "B", "page_content": "Content B"},
            {"source_guid": "A", "page_content": "Content A"},
        ]

        # Input data: First record has source_guid "A" (index 1 in source_data)
        input_data = [
            {
                "target_id": "target-1",
                "source_guid": "A",  # Points to source_data[1], not source_data[0]
                "content": {"question": "Q1"},
            },
            {
                "target_id": "target-2",
                "source_guid": "B",
                "content": {"question": "Q2"},
            },
        ]

        preparator = BatchTaskPreparator()

        # Should NOT raise PreFlightValidationError
        # because it correctly looks up source_guid "A" (not index 0)
        with patch("agent_actions.llm.batch.processing.preparator.logger"):
            result = preparator.prepare_tasks(
                agent_config=agent_config,
                data=input_data,
                provider=mock_provider,
                source_data=source_data,
            )

        assert result.stats.error_items == 0, "Preflight should succeed with correct lookup"
        assert result.stats.included_items == 2
