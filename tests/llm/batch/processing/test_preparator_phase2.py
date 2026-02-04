"""
Tests for Phase 2 guard evaluation in BatchTaskPreparator.

Related: GitHub Issue #875, #889 (Phase 1b)
"""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.core.batch_models import BatchTaskPreparationStats
from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys
from agent_actions.input.preprocessing.filtering.evaluator import GuardResult


class TestHasContextDependentGuard:
    """Tests for _has_context_dependent_guard method."""

    @pytest.fixture
    def preparator(self):
        return BatchTaskPreparator()

    def test_no_guard_returns_false(self, preparator):
        """No guard config returns False."""
        agent_config = {}
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_guard_without_clause_returns_false(self, preparator):
        """Guard without clause returns False."""
        agent_config = {"guard": {"behavior": "filter"}}
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_simple_guard_returns_false(self, preparator):
        """Simple guard without context refs returns False."""
        agent_config = {"guard": {"clause": "x > 10", "behavior": "filter"}}
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_source_reference_returns_true(self, preparator):
        """Guard with source.* reference returns True."""
        agent_config = {"guard": {"clause": "source.type == 'pdf'", "behavior": "filter"}}
        assert preparator._has_context_dependent_guard(agent_config) is True

    def test_source_template_reference_returns_true(self, preparator):
        """Guard with {source reference returns True."""
        agent_config = {"guard": {"clause": "{source.count} > 5", "behavior": "filter"}}
        assert preparator._has_context_dependent_guard(agent_config) is True

    def test_passthrough_field_reference_returns_true(self, preparator):
        """Guard referencing passthrough field returns True."""
        agent_config = {
            "guard": {"clause": "original_title != ''", "behavior": "filter"},
            "context_scope": {"passthrough": ["original_title"]},
        }
        assert preparator._has_context_dependent_guard(agent_config) is True

    def test_passthrough_dict_field_reference_returns_true(self, preparator):
        """Guard referencing passthrough field (dict format) returns True."""
        agent_config = {
            "guard": {"clause": "doc_id != ''", "behavior": "filter"},
            "context_scope": {"passthrough": [{"field": "doc_id"}]},
        }
        assert preparator._has_context_dependent_guard(agent_config) is True

    def test_observe_field_reference_returns_true(self, preparator):
        """Guard referencing observe field returns True."""
        agent_config = {
            "guard": {"clause": "observed_field > 0", "behavior": "filter"},
            "context_scope": {"observe": ["observed_field"]},
        }
        assert preparator._has_context_dependent_guard(agent_config) is True

    def test_unrelated_passthrough_returns_false(self, preparator):
        """Guard not referencing any passthrough field returns False."""
        agent_config = {
            "guard": {"clause": "x > 10", "behavior": "filter"},
            "context_scope": {"passthrough": ["other_field"]},
        }
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_datasource_not_matched_as_source(self, preparator):
        """Guard with 'datasource.id' should NOT trigger source detection (word boundary)."""
        agent_config = {"guard": {"clause": "datasource.id != ''", "behavior": "filter"}}
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_my_source_not_matched_as_source(self, preparator):
        """Guard with 'my_source.field' should NOT trigger source detection (word boundary)."""
        agent_config = {"guard": {"clause": "my_source.field > 0", "behavior": "filter"}}
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_passthrough_field_word_boundary(self, preparator):
        """Passthrough field 'id' should NOT match 'valid' or 'grid' (word boundary)."""
        agent_config = {
            "guard": {"clause": "valid == True and grid > 0", "behavior": "filter"},
            "context_scope": {"passthrough": ["id"]},
        }
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_passthrough_field_exact_match(self, preparator):
        """Passthrough field 'id' SHOULD match when used as standalone identifier."""
        agent_config = {
            "guard": {"clause": "id != '' and status == 'active'", "behavior": "filter"},
            "context_scope": {"passthrough": ["id"]},
        }
        assert preparator._has_context_dependent_guard(agent_config) is True

    def test_field_in_string_literal_not_matched(self, preparator):
        """Field name inside string literal should NOT trigger detection (AST-based)."""
        agent_config = {
            "guard": {"clause": "message == 'check your id here'", "behavior": "filter"},
            "context_scope": {"passthrough": ["id"]},
        }
        # "id" appears in string literal, not as an identifier
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_source_in_string_literal_not_matched(self, preparator):
        """'source' in string literal should NOT trigger detection."""
        agent_config = {
            "guard": {"clause": "error == 'invalid source data'", "behavior": "filter"},
        }
        assert preparator._has_context_dependent_guard(agent_config) is False

    def test_source_as_identifier_matched(self, preparator):
        """'source' as actual identifier SHOULD trigger detection."""
        agent_config = {
            "guard": {"clause": "source.type == 'pdf'", "behavior": "filter"},
        }
        assert preparator._has_context_dependent_guard(agent_config) is True


class TestExtractClauseIdentifiers:
    """Tests for AST-based identifier extraction."""

    @pytest.fixture
    def preparator(self):
        return BatchTaskPreparator()

    def test_simple_identifiers(self, preparator):
        """Extract simple identifiers."""
        ids = preparator._extract_clause_identifiers("x > 10 and y < 20")
        assert "x" in ids
        assert "y" in ids

    def test_attribute_access_extracts_root(self, preparator):
        """Extract root name from attribute access."""
        ids = preparator._extract_clause_identifiers("source.type == 'pdf'")
        assert "source" in ids

    def test_string_literals_ignored(self, preparator):
        """Identifiers in string literals are not extracted."""
        ids = preparator._extract_clause_identifiers("message == 'check id'")
        assert "message" in ids
        assert "id" not in ids  # "id" is inside string, not an identifier

    def test_invalid_syntax_returns_empty(self, preparator):
        """Invalid Python syntax returns empty set."""
        # Template syntax like ${source.type} is not valid Python
        ids = preparator._extract_clause_identifiers("${source.type}")
        assert ids == set()


class TestPhase2GuardEvaluation:
    """Tests for Phase 2 guard evaluation in _prepare_single_task."""

    @pytest.fixture
    def preparator(self):
        return BatchTaskPreparator()

    @pytest.fixture
    def mock_provider(self):
        provider = MagicMock()
        provider.prepare_tasks.return_value = []
        return provider

    @pytest.fixture
    def mock_prep_result(self):
        """Create a mock PromptPreparationResult."""
        mock_result = MagicMock()
        mock_result.llm_context = {"content": "test"}
        mock_result.formatted_prompt = "Test prompt"
        mock_result.passthrough_fields = {"field1": "value1"}
        mock_result.prompt_context = {"ctx": "data"}
        return mock_result

    def test_phase2_guard_passes(self, preparator, mock_prep_result):
        """Phase 2 guard that passes returns task."""
        # Mock the evaluator to return passed
        with patch.object(preparator, "_has_context_dependent_guard", return_value=True):
            with patch(
                "agent_actions.llm.batch.processing.preparator.get_guard_evaluator"
            ) as mock_get_eval:
                mock_evaluator = MagicMock()
                mock_evaluator.evaluate_with_context.return_value = GuardResult.passed()
                mock_get_eval.return_value = mock_evaluator

                # Mock PromptPreparationService via the module it's imported from
                with patch("agent_actions.prompt.service.PromptPreparationService") as mock_prep:
                    mock_prep.prepare_prompt_with_context.return_value = mock_prep_result

                    context_map = {"test_id": {"content": "test"}}
                    stats = BatchTaskPreparationStats(total_items=1)

                    result = preparator._prepare_single_task(
                        _row={"content": "test"},
                        row_content={"content": "test"},
                        custom_id="test_id",
                        agent_config={"guard": {"clause": "source.type == 'pdf'"}},
                        guard_config={"clause": "source.type == 'pdf'"},
                        output_directory="/tmp",
                        batch_name="test.json",
                        tools_path=None,
                        context_map_builder=context_map,
                        stats=stats,
                    )

                    # Should return task
                    assert result is not None
                    assert result["target_id"] == "test_id"
                    assert stats.phase2_filtered_items == 0
                    assert stats.phase2_skipped_items == 0

    def test_phase2_guard_filters(self, preparator):
        """Phase 2 guard that filters returns None and updates stats."""
        mock_prep_result = MagicMock()
        mock_prep_result.llm_context = {"content": "test"}
        mock_prep_result.formatted_prompt = "Test prompt"
        mock_prep_result.passthrough_fields = {}
        mock_prep_result.prompt_context = {}

        with patch.object(preparator, "_has_context_dependent_guard", return_value=True):
            with patch(
                "agent_actions.llm.batch.processing.preparator.get_guard_evaluator"
            ) as mock_get_eval:
                mock_evaluator = MagicMock()
                mock_evaluator.evaluate_with_context.return_value = GuardResult.filtered()
                mock_get_eval.return_value = mock_evaluator

                with patch("agent_actions.prompt.service.PromptPreparationService") as mock_prep:
                    mock_prep.prepare_prompt_with_context.return_value = mock_prep_result

                    context_map = {"test_id": {"content": "test"}}
                    stats = BatchTaskPreparationStats(total_items=1)

                    result = preparator._prepare_single_task(
                        _row={"content": "test"},
                        row_content={"content": "test"},
                        custom_id="test_id",
                        agent_config={"guard": {"clause": "source.count > 100"}},
                        guard_config={"clause": "source.count > 100", "behavior": "filter"},
                        output_directory="/tmp",
                        batch_name="test.json",
                        tools_path=None,
                        context_map_builder=context_map,
                        stats=stats,
                    )

                    # Should return None (filtered)
                    assert result is None
                    assert stats.phase2_filtered_items == 1
                    assert stats.phase2_skipped_items == 0
                    assert context_map["test_id"][ContextMetaKeys.FILTER_STATUS] == "filtered"
                    assert context_map["test_id"][ContextMetaKeys.FILTER_PHASE] == "phase2"

    def test_phase2_guard_skips(self, preparator):
        """Phase 2 guard that skips returns None and updates stats."""
        mock_prep_result = MagicMock()
        mock_prep_result.llm_context = {"content": "test"}
        mock_prep_result.formatted_prompt = "Test prompt"
        mock_prep_result.passthrough_fields = {}
        mock_prep_result.prompt_context = {}

        with patch.object(preparator, "_has_context_dependent_guard", return_value=True):
            with patch(
                "agent_actions.llm.batch.processing.preparator.get_guard_evaluator"
            ) as mock_get_eval:
                mock_evaluator = MagicMock()
                mock_evaluator.evaluate_with_context.return_value = GuardResult.skipped()
                mock_get_eval.return_value = mock_evaluator

                with patch("agent_actions.prompt.service.PromptPreparationService") as mock_prep:
                    mock_prep.prepare_prompt_with_context.return_value = mock_prep_result

                    context_map = {"test_id": {"content": "test"}}
                    stats = BatchTaskPreparationStats(total_items=1)

                    result = preparator._prepare_single_task(
                        _row={"content": "test"},
                        row_content={"content": "test"},
                        custom_id="test_id",
                        agent_config={"guard": {"clause": "source.count > 100"}},
                        guard_config={"clause": "source.count > 100", "behavior": "skip"},
                        output_directory="/tmp",
                        batch_name="test.json",
                        tools_path=None,
                        context_map_builder=context_map,
                        stats=stats,
                    )

                    # Should return None (skipped)
                    assert result is None
                    assert stats.phase2_filtered_items == 0
                    assert stats.phase2_skipped_items == 1
                    assert context_map["test_id"][ContextMetaKeys.FILTER_STATUS] == "skipped"
                    assert context_map["test_id"][ContextMetaKeys.FILTER_PHASE] == "phase2"

    def test_non_context_dependent_guard_skips_phase2(self, preparator):
        """Non-context-dependent guard skips Phase 2 evaluation."""
        mock_prep_result = MagicMock()
        mock_prep_result.llm_context = {"content": "test"}
        mock_prep_result.formatted_prompt = "Test prompt"
        mock_prep_result.passthrough_fields = {}
        mock_prep_result.prompt_context = {}

        with patch.object(preparator, "_has_context_dependent_guard", return_value=False):
            with patch(
                "agent_actions.llm.batch.processing.preparator.get_guard_evaluator"
            ) as mock_get_eval:
                mock_evaluator = MagicMock()
                mock_get_eval.return_value = mock_evaluator

                with patch("agent_actions.prompt.service.PromptPreparationService") as mock_prep:
                    mock_prep.prepare_prompt_with_context.return_value = mock_prep_result

                    context_map = {"test_id": {"content": "test"}}
                    stats = BatchTaskPreparationStats(total_items=1)

                    result = preparator._prepare_single_task(
                        _row={"content": "test"},
                        row_content={"content": "test"},
                        custom_id="test_id",
                        agent_config={"guard": {"clause": "x > 10"}},
                        guard_config={"clause": "x > 10", "behavior": "filter"},
                        output_directory="/tmp",
                        batch_name="test.json",
                        tools_path=None,
                        context_map_builder=context_map,
                        stats=stats,
                    )

                    # Should return task (Phase 2 not evaluated)
                    assert result is not None
                    # Phase 2 evaluator should NOT be called
                    mock_evaluator.evaluate_with_context.assert_not_called()


class TestBatchTaskPreparationStats:
    """Tests for updated BatchTaskPreparationStats."""

    def test_phase2_fields_exist(self):
        """Stats has Phase 2 tracking fields."""
        stats = BatchTaskPreparationStats(total_items=10)
        assert hasattr(stats, "phase2_filtered_items")
        assert hasattr(stats, "phase2_skipped_items")
        assert stats.phase2_filtered_items == 0
        assert stats.phase2_skipped_items == 0

    def test_total_filtered_combines_phases(self):
        """total_filtered includes both phases."""
        stats = BatchTaskPreparationStats(
            total_items=10,
            filtered_items=3,
            phase2_filtered_items=2,
        )
        assert stats.total_filtered == 5

    def test_total_skipped_combines_phases(self):
        """total_skipped includes both phases."""
        stats = BatchTaskPreparationStats(
            total_items=10,
            skipped_items=2,
            phase2_skipped_items=1,
        )
        assert stats.total_skipped == 3


class TestContextMetaKeysPhase:
    """Tests for FILTER_PHASE constant."""

    def test_filter_phase_key_exists(self):
        """FILTER_PHASE key is defined."""
        assert hasattr(ContextMetaKeys, "FILTER_PHASE")
        assert ContextMetaKeys.FILTER_PHASE == "_batch_filter_phase"

    def test_all_internal_keys_includes_phase(self):
        """all_internal_keys includes FILTER_PHASE."""
        keys = ContextMetaKeys.all_internal_keys()
        assert ContextMetaKeys.FILTER_PHASE in keys
