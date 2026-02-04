"""
Tests for BatchTaskPreparator unified guard evaluation.

Related: GitHub Issue #875, #890 (Phase 2)

The simplified design uses TaskPreparer for unified guard evaluation:
- ONE guard check with full context (like SQL WHERE clause)
- No two-phase complexity
- Same code path as online mode
"""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.core.batch_models import BatchTaskPreparationStats
from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys
from agent_actions.processing.prepared_task import GuardStatus, PreparedTask, PreparationContext


class TestBatchTaskPreparatorUsesTaskPreparer:
    """Tests that BatchTaskPreparator uses TaskPreparer for unified preparation."""

    @pytest.fixture
    def preparator(self):
        return BatchTaskPreparator()

    @pytest.fixture
    def mock_provider(self):
        provider = MagicMock()
        provider.prepare_tasks.return_value = []
        return provider

    @pytest.fixture
    def basic_agent_config(self):
        return {
            "agent_type": "test_agent",
            "prompt": "Test prompt: {{ content }}",
        }

    def test_process_single_item_uses_task_preparer(self, preparator, basic_agent_config):
        """Test that _process_single_item delegates to TaskPreparer."""
        # Create a PreparedTask that would be returned by TaskPreparer
        mock_prepared = PreparedTask(
            target_id="test_id",
            source_guid="guid-123",
            formatted_prompt="Rendered prompt",
            llm_context={"content": "test"},
            passthrough_fields={"pass": "through"},
            guard_status=GuardStatus.PASSED,
        )

        prep_context = PreparationContext(
            agent_config=basic_agent_config,
            agent_name="test_agent",
            is_first_stage=False,
        )

        mock_task_preparer = MagicMock()
        mock_task_preparer.prepare.return_value = mock_prepared

        context_map = {}
        stats = BatchTaskPreparationStats(total_items=1)

        result = preparator._process_single_item(
            row={"content": "test", "target_id": "test_id"},
            prep_context=prep_context,
            task_preparer=mock_task_preparer,
            context_map_builder=context_map,
            stats=stats,
        )

        # Should return task dict
        assert result is not None
        assert result["target_id"] == "test_id"
        assert result["prompt"] == "Rendered prompt"
        assert result["content"] == {"content": "test"}
        assert (
            stats.included_items == 0
        )  # Incremented in prepare_tasks loop, not _process_single_item

    def test_process_single_item_guard_filtered(self, preparator, basic_agent_config):
        """Test that _process_single_item handles filtered guard status."""
        mock_prepared = PreparedTask(
            target_id="test_id",
            source_guid="guid-123",
            guard_status=GuardStatus.FILTERED,
            guard_behavior="filter",
        )

        prep_context = PreparationContext(
            agent_config=basic_agent_config,
            agent_name="test_agent",
            is_first_stage=False,
        )

        mock_task_preparer = MagicMock()
        mock_task_preparer.prepare.return_value = mock_prepared

        context_map = {}
        stats = BatchTaskPreparationStats(total_items=1)

        result = preparator._process_single_item(
            row={"content": "test", "target_id": "test_id"},
            prep_context=prep_context,
            task_preparer=mock_task_preparer,
            context_map_builder=context_map,
            stats=stats,
        )

        # Should return None (filtered)
        assert result is None
        assert stats.filtered_items == 1
        assert stats.skipped_items == 0
        assert context_map["test_id"][ContextMetaKeys.FILTER_STATUS] == "filtered"

    def test_process_single_item_guard_skipped(self, preparator, basic_agent_config):
        """Test that _process_single_item handles skipped guard status."""
        mock_prepared = PreparedTask(
            target_id="test_id",
            source_guid="guid-123",
            guard_status=GuardStatus.SKIPPED,
            guard_behavior="skip",
        )

        prep_context = PreparationContext(
            agent_config=basic_agent_config,
            agent_name="test_agent",
            is_first_stage=False,
        )

        mock_task_preparer = MagicMock()
        mock_task_preparer.prepare.return_value = mock_prepared

        context_map = {}
        stats = BatchTaskPreparationStats(total_items=1)

        result = preparator._process_single_item(
            row={"content": "test", "target_id": "test_id"},
            prep_context=prep_context,
            task_preparer=mock_task_preparer,
            context_map_builder=context_map,
            stats=stats,
        )

        # Should return None (skipped)
        assert result is None
        assert stats.filtered_items == 0
        assert stats.skipped_items == 1
        assert context_map["test_id"][ContextMetaKeys.FILTER_STATUS] == "skipped"

    def test_process_single_item_stores_passthrough_fields(self, preparator, basic_agent_config):
        """Test that _process_single_item stores passthrough_fields in context map."""
        mock_prepared = PreparedTask(
            target_id="test_id",
            source_guid="guid-123",
            formatted_prompt="Rendered prompt",
            llm_context={"content": "test"},
            passthrough_fields={"original_title": "Test Title", "doc_id": "123"},
            guard_status=GuardStatus.PASSED,
        )

        prep_context = PreparationContext(
            agent_config=basic_agent_config,
            agent_name="test_agent",
            is_first_stage=False,
        )

        mock_task_preparer = MagicMock()
        mock_task_preparer.prepare.return_value = mock_prepared

        context_map = {}
        stats = BatchTaskPreparationStats(total_items=1)

        result = preparator._process_single_item(
            row={"content": "test", "target_id": "test_id"},
            prep_context=prep_context,
            task_preparer=mock_task_preparer,
            context_map_builder=context_map,
            stats=stats,
        )

        assert result is not None
        # Check passthrough fields stored
        assert ContextMetaKeys.PASSTHROUGH_FIELDS in context_map["test_id"]
        stored_passthrough = context_map["test_id"][ContextMetaKeys.PASSTHROUGH_FIELDS]
        assert stored_passthrough["original_title"] == "Test Title"
        assert stored_passthrough["doc_id"] == "123"

    def test_process_single_item_generates_target_id_if_missing(
        self, preparator, basic_agent_config
    ):
        """Test that _process_single_item generates target_id if not in row."""
        mock_prepared = PreparedTask(
            target_id="generated_id",  # Will be overwritten
            source_guid="guid-123",
            formatted_prompt="Rendered prompt",
            llm_context={"content": "test"},
            guard_status=GuardStatus.PASSED,
        )

        prep_context = PreparationContext(
            agent_config=basic_agent_config,
            agent_name="test_agent",
            is_first_stage=False,
        )

        mock_task_preparer = MagicMock()
        mock_task_preparer.prepare.return_value = mock_prepared

        context_map = {}
        stats = BatchTaskPreparationStats(total_items=1)

        # Row without target_id
        row = {"content": "test"}

        with patch("agent_actions.llm.batch.processing.preparator.IDGenerator") as mock_id_gen:
            mock_id_gen.generate_target_id.return_value = "auto_generated_id"

            result = preparator._process_single_item(
                row=row,
                prep_context=prep_context,
                task_preparer=mock_task_preparer,
                context_map_builder=context_map,
                stats=stats,
            )

        # Should have generated target_id
        assert "auto_generated_id" in context_map
        mock_id_gen.generate_target_id.assert_called_once()


class TestBatchTaskPreparationStats:
    """Tests for updated BatchTaskPreparationStats."""

    def test_phase2_fields_exist(self):
        """Stats has Phase 2 tracking fields (for backward compatibility)."""
        stats = BatchTaskPreparationStats(total_items=10)
        assert hasattr(stats, "phase2_filtered_items")
        assert hasattr(stats, "phase2_skipped_items")
        assert stats.phase2_filtered_items == 0
        assert stats.phase2_skipped_items == 0

    def test_total_filtered_combines_phases(self):
        """total_filtered includes both phases (backward compatibility)."""
        stats = BatchTaskPreparationStats(
            total_items=10,
            filtered_items=3,
            phase2_filtered_items=2,
        )
        assert stats.total_filtered == 5

    def test_total_skipped_combines_phases(self):
        """total_skipped includes both phases (backward compatibility)."""
        stats = BatchTaskPreparationStats(
            total_items=10,
            skipped_items=2,
            phase2_skipped_items=1,
        )
        assert stats.total_skipped == 3


class TestContextMetaKeysPhase:
    """Tests for FILTER_PHASE constant (backward compatibility)."""

    def test_filter_phase_key_exists(self):
        """FILTER_PHASE key is defined."""
        assert hasattr(ContextMetaKeys, "FILTER_PHASE")
        assert ContextMetaKeys.FILTER_PHASE == "_batch_filter_phase"

    def test_all_internal_keys_includes_phase(self):
        """all_internal_keys includes FILTER_PHASE."""
        keys = ContextMetaKeys.all_internal_keys()
        assert ContextMetaKeys.FILTER_PHASE in keys


class TestBatchTaskPreparatorBackwardCompatibility:
    """Tests for backward compatibility of deprecated parameters."""

    def test_deprecated_filter_service_emits_warning(self):
        """filter_service parameter emits deprecation warning."""
        mock_filter_service = MagicMock()
        with pytest.warns(DeprecationWarning, match="filter_service is deprecated"):
            preparator = BatchTaskPreparator(filter_service=mock_filter_service)
        assert preparator is not None

    def test_deprecated_guard_handler_emits_warning(self):
        """guard_handler parameter emits deprecation warning."""
        mock_guard_handler = MagicMock()
        with pytest.warns(DeprecationWarning, match="guard_handler is deprecated"):
            preparator = BatchTaskPreparator(guard_handler=mock_guard_handler)
        assert preparator is not None

    def test_storage_backend_passed_to_context(self):
        """storage_backend is stored for use in PreparationContext."""
        mock_storage = MagicMock()
        preparator = BatchTaskPreparator(storage_backend=mock_storage)
        assert preparator.storage_backend is mock_storage
