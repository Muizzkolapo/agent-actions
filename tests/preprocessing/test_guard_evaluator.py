"""
Tests for the unified GuardEvaluator.

Related: GitHub Issue #875, #888 (Phase 1a)
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import (
    GuardEvaluator,
    GuardResult,
)
from agent_actions.input.preprocessing.filtering.guard_filter import (
    FilterResult,
    GuardFilter,
)


class TestGuardResult:
    """Tests for GuardResult dataclass."""

    def test_skipped_with_error(self):
        result = GuardResult.skipped(error="test error")
        assert result.should_execute is False
        assert result.behavior == "skip"
        assert result.error == "test error"

    def test_from_filter_result_success_matched(self):
        filter_result = FilterResult(success=True, matched=True)
        result = GuardResult.from_filter_result(filter_result, "filter", True)
        assert result.should_execute is True
        assert result.behavior is None

    def test_from_filter_result_success_not_matched_filter(self):
        filter_result = FilterResult(success=True, matched=False)
        result = GuardResult.from_filter_result(filter_result, "filter", True)
        assert result.should_execute is False
        assert result.behavior == "filter"

    def test_from_filter_result_success_not_matched_skip(self):
        filter_result = FilterResult(success=True, matched=False)
        result = GuardResult.from_filter_result(filter_result, "skip", True)
        assert result.should_execute is False
        assert result.behavior == "skip"

    def test_from_filter_result_failure_passthrough_on_error(self):
        filter_result = FilterResult(success=False, matched=False, error="parse error")
        result = GuardResult.from_filter_result(filter_result, "filter", passthrough_on_error=True)
        assert result.should_execute is True
        assert result.behavior is None

    def test_from_filter_result_failure_no_passthrough(self):
        filter_result = FilterResult(success=False, matched=False, error="parse error")
        result = GuardResult.from_filter_result(filter_result, "filter", passthrough_on_error=False)
        assert result.should_execute is False
        assert result.behavior == "filter"


class TestGuardEvaluator:
    """Tests for GuardEvaluator class."""

    @pytest.fixture
    def mock_guard_filter(self):
        """Create a mock GuardFilter."""
        mock = MagicMock(spec=GuardFilter)
        return mock

    @pytest.fixture
    def evaluator(self, mock_guard_filter):
        """Create evaluator with mock filter."""
        return GuardEvaluator(guard_filter=mock_guard_filter)

    def test_evaluate_early_no_guard(self, evaluator, mock_guard_filter):
        """No guard config returns passed."""
        result = evaluator.evaluate_early({"field": "value"}, None)
        assert result.should_execute is True
        mock_guard_filter.filter_item.assert_not_called()

    def test_evaluate_early_no_clause(self, evaluator, mock_guard_filter):
        """Guard config without clause returns passed."""
        result = evaluator.evaluate_early({"field": "value"}, {"behavior": "filter"})
        assert result.should_execute is True
        mock_guard_filter.filter_item.assert_not_called()

    def test_evaluate_early_action_scope_skipped(self, evaluator, mock_guard_filter):
        """Action-scope guards are skipped (only item-level guards evaluated)."""
        guard_config = {"clause": "x > 1", "scope": "action"}
        result = evaluator.evaluate_early({"x": 5}, guard_config)
        assert result.should_execute is True
        mock_guard_filter.filter_item.assert_not_called()

    def test_evaluate_early_guard_passes(self, evaluator, mock_guard_filter):
        """Guard that matches returns passed."""
        mock_guard_filter.filter_item.return_value = FilterResult(success=True, matched=True)
        guard_config = {"clause": "x > 1", "scope": "item", "behavior": "filter"}

        result = evaluator.evaluate_early({"x": 5}, guard_config)

        assert result.should_execute is True
        mock_guard_filter.filter_item.assert_called_once()

    def test_evaluate_early_guard_filters(self, evaluator, mock_guard_filter):
        """Guard that doesn't match with filter behavior returns filtered."""
        mock_guard_filter.filter_item.return_value = FilterResult(success=True, matched=False)
        guard_config = {"clause": "x > 10", "scope": "item", "behavior": "filter"}

        result = evaluator.evaluate_early({"x": 5}, guard_config)

        assert result.should_execute is False
        assert result.behavior == "filter"

    def test_evaluate_early_guard_skips(self, evaluator, mock_guard_filter):
        """Guard that doesn't match with skip behavior returns skipped."""
        mock_guard_filter.filter_item.return_value = FilterResult(success=True, matched=False)
        guard_config = {"clause": "x > 10", "scope": "item", "behavior": "skip"}

        result = evaluator.evaluate_early({"x": 5}, guard_config)

        assert result.should_execute is False
        assert result.behavior == "skip"

    def test_evaluate_backward_compatible_format(self, evaluator, mock_guard_filter):
        """evaluate() returns (should_execute, behavior) tuple format."""
        mock_guard_filter.filter_item.return_value = FilterResult(success=True, matched=False)
        guard_config = {"clause": "x > 10", "scope": "item", "behavior": "skip"}

        should_execute, behavior = evaluator.evaluate({"x": 5}, guard_config)

        assert should_execute is False
        assert behavior == "skip"

    def test_should_skip_with_skip_behavior(self, evaluator, mock_guard_filter):
        """should_skip returns True when guard fails with skip behavior."""
        mock_guard_filter.filter_item.return_value = FilterResult(success=True, matched=False)
        agent_config = {"guard": {"clause": "x > 10", "scope": "item", "behavior": "skip"}}

        result = evaluator.should_skip(agent_config, {"x": 5})

        assert result is True

    def test_should_skip_with_filter_behavior(self, evaluator, mock_guard_filter):
        """should_skip returns False for filter behavior (not a skip)."""
        agent_config = {"guard": {"clause": "x > 10", "scope": "item", "behavior": "filter"}}

        result = evaluator.should_skip(agent_config, {"x": 5})

        assert result is False  # Not skip behavior
        mock_guard_filter.filter_item.assert_not_called()

    def test_should_filter_with_filter_behavior(self, evaluator, mock_guard_filter):
        """should_filter returns True when guard fails with filter behavior."""
        mock_guard_filter.filter_item.return_value = FilterResult(success=True, matched=False)
        agent_config = {"guard": {"clause": "x > 10", "scope": "item", "behavior": "filter"}}

        result = evaluator.should_filter(agent_config, {"x": 5})

        assert result is True

    def test_should_filter_with_skip_behavior(self, evaluator, mock_guard_filter):
        """should_filter returns False for skip behavior (not a filter)."""
        agent_config = {"guard": {"clause": "x > 10", "scope": "item", "behavior": "skip"}}

        result = evaluator.should_filter(agent_config, {"x": 5})

        assert result is False  # Not filter behavior
        mock_guard_filter.filter_item.assert_not_called()

    def test_prepare_eval_context_with_nested_content(self, evaluator):
        """Nested content structure is properly extracted with ALL top-level metadata."""
        context = {
            "source_guid": "abc123",
            "target_id": "target1",
            "lineage": {"parent_id": "parent123"},
            "custom_field": "custom_value",
            "content": {"field1": "value1", "field2": "value2"},
        }

        result = evaluator._prepare_eval_context(context)

        # Content fields should be accessible at top level
        assert result["field1"] == "value1"
        assert result["field2"] == "value2"
        # ALL top-level metadata should be preserved (not just whitelisted keys)
        assert result["source_guid"] == "abc123"
        assert result["target_id"] == "target1"
        assert result["lineage"] == {"parent_id": "parent123"}
        assert result["custom_field"] == "custom_value"
        # content key itself should NOT be in result (flattened)
        assert "content" not in result

    def test_prepare_eval_context_flat_dict(self, evaluator):
        """Flat dict is returned as-is."""
        context = {"field1": "value1", "field2": "value2"}

        result = evaluator._prepare_eval_context(context)

        assert result == context

    def test_prepare_eval_context_non_dict(self, evaluator):
        """Non-dict is wrapped in _raw key."""
        result = evaluator._prepare_eval_context("some string")

        assert result == {"_raw": "some string"}

    def test_build_evaluation_context_with_dict_item(self, evaluator):
        """Dict item is merged with context."""
        item = {"field1": "value1"}
        context = {"ctx_field": "ctx_value"}

        result = evaluator._build_evaluation_context(item, context)

        assert result["field1"] == "value1"
        assert result["ctx_field"] == "ctx_value"

    def test_build_evaluation_context_preserves_metadata_with_content(self, evaluator):
        """Top-level metadata is preserved when item has content dict."""
        item = {
            "doc_type": "pdf",
            "source_guid": "abc123",
            "content": {"text": "hello", "page": 1},
        }
        context = {"passthrough_field": "value"}

        result = evaluator._build_evaluation_context(item, context)

        # Content fields should be accessible
        assert result["text"] == "hello"
        assert result["page"] == 1
        # Top-level metadata should be preserved
        assert result["doc_type"] == "pdf"
        assert result["source_guid"] == "abc123"
        # Context should be present
        assert result["passthrough_field"] == "value"
        # content key itself should NOT be present (flattened)
        assert "content" not in result

    def test_build_evaluation_context_with_non_dict_item(self, evaluator):
        """Non-dict item is preserved in _raw key (parity with evaluate_early)."""
        item = "raw string content"
        context = {"ctx_field": "ctx_value"}

        result = evaluator._build_evaluation_context(item, context)

        assert result["_raw"] == "raw string content"
        assert result["ctx_field"] == "ctx_value"

    def test_build_evaluation_context_with_none_item(self, evaluator):
        """None item doesn't add _raw key."""
        context = {"ctx_field": "ctx_value"}

        result = evaluator._build_evaluation_context(None, context)

        assert "_raw" not in result
        assert result["ctx_field"] == "ctx_value"


class TestOutputFieldPromotion:
    """Tests for output_field promotion in guard evaluation context.

    When an upstream action declares output_field, the field value should be
    promoted to top-level in the evaluation context so guards can reference
    it directly (e.g., `severity != "low"` instead of `assess_severity.severity != "low"`).
    """

    @pytest.fixture
    def mock_guard_filter(self):
        mock = MagicMock(spec=GuardFilter)
        return mock

    @pytest.fixture
    def evaluator(self, mock_guard_filter):
        return GuardEvaluator(guard_filter=mock_guard_filter)

    def test_promoted_output_field_in_eval_context(self, evaluator):
        """Promoted output_field is accessible as top-level key in evaluation context."""
        # Simulate field_context after output_field promotion in task_preparer
        context = {
            "assess_severity": {"severity": "high"},
            "severity": "high",  # Promoted by task_preparer
        }

        result = evaluator._build_evaluation_context(
            item={"content": {"text": "test"}},
            context=context,
        )

        # severity should be a top-level key (promoted from assess_severity.severity)
        assert "severity" in result
        assert result["severity"] == "high"
        # Original namespace should also be accessible
        assert "assess_severity" in result
        assert result["assess_severity"]["severity"] == "high"

    def test_dot_notation_in_eval_context(self, evaluator):
        """Dot notation to access nested output_field values works in the eval context."""
        context = {
            "assess_severity": {"severity": "high"},
        }

        result = evaluator._build_evaluation_context(
            item={"content": {"text": "test"}},
            context=context,
        )

        # assess_severity is a top-level dict, so dot notation should resolve
        from agent_actions.utils.dict import get_nested_value

        assert get_nested_value(result, "assess_severity.severity") == "high"

    def test_guard_receives_promoted_field(self, evaluator, mock_guard_filter):
        """Guard filter receives the promoted output_field in data dict."""
        mock_guard_filter.filter_item.return_value = FilterResult(success=True, matched=True)

        context = {
            "assess_severity": {"severity": "high"},
            "severity": "high",  # Promoted
        }
        guard_config = {"clause": 'severity != "low"', "scope": "item", "behavior": "skip"}

        evaluator.evaluate_with_context(
            item={"content": {}},
            guard_config=guard_config,
            context=context,
        )

        # Verify filter was called with data containing promoted field
        call_args = mock_guard_filter.filter_item.call_args[0][0]
        assert "severity" in call_args.data
        assert call_args.data["severity"] == "high"


class TestOutputFieldPromotionInTaskPreparer:
    """Tests for output_field promotion logic in TaskPreparer._load_full_context."""

    def test_promote_output_field_to_top_level(self):
        """output_field values from dependency_configs are promoted to top-level in field_context."""
        from unittest.mock import patch

        from agent_actions.processing.prepared_task import PreparationContext
        from agent_actions.processing.task_preparer import TaskPreparer

        preparer = TaskPreparer()

        # Mock build_field_context_with_history to return controlled field_context
        mock_field_context = {
            "assess_severity": {"severity": "high"},
            "source": {"text": "input"},
        }

        context = PreparationContext(
            agent_config={"context_scope": {}},
            agent_name="draft_response",
            dependency_configs={
                "assess_severity": {"output_field": "severity", "idx": 0},
                "other_action": {"idx": 1},
            },
        )

        with patch(
            "agent_actions.prompt.context.scope_builder.build_field_context_with_history",
            return_value=mock_field_context,
        ):
            result = preparer._load_full_context(
                content={"text": "test"},
                source_content={"text": "source"},
                context=context,
                current_item=None,
            )

        # output_field value should be promoted to top-level
        assert "severity" in result
        assert result["severity"] == "high"
        # Original namespace should still exist
        assert result["assess_severity"] == {"severity": "high"}

    def test_output_field_collision_skips_promotion(self):
        """When output_field name collides with existing field, promotion is skipped."""
        from unittest.mock import patch

        from agent_actions.processing.prepared_task import PreparationContext
        from agent_actions.processing.task_preparer import TaskPreparer

        preparer = TaskPreparer()

        # "severity" already exists as a top-level field
        mock_field_context = {
            "assess_severity": {"severity": "high"},
            "severity": "existing_value",  # Already present
        }

        context = PreparationContext(
            agent_config={"context_scope": {}},
            agent_name="draft_response",
            dependency_configs={
                "assess_severity": {"output_field": "severity", "idx": 0},
            },
        )

        with patch(
            "agent_actions.prompt.context.scope_builder.build_field_context_with_history",
            return_value=mock_field_context,
        ):
            result = preparer._load_full_context(
                content={},
                source_content={},
                context=context,
                current_item=None,
            )

        # Should NOT overwrite existing field
        assert result["severity"] == "existing_value"

    def test_promote_output_field_from_list_dep_data(self):
        """output_field promotion works when dep_data is a single-item list (common storage shape)."""
        from unittest.mock import patch

        from agent_actions.processing.prepared_task import PreparationContext
        from agent_actions.processing.task_preparer import TaskPreparer

        preparer = TaskPreparer()

        mock_field_context = {
            "assess_severity": [{"severity": "high"}],  # List shape from storage
            "source": {"text": "input"},
        }

        context = PreparationContext(
            agent_config={"context_scope": {}},
            agent_name="draft_response",
            dependency_configs={
                "assess_severity": {"output_field": "severity", "idx": 0},
            },
        )

        with patch(
            "agent_actions.prompt.context.scope_builder.build_field_context_with_history",
            return_value=mock_field_context,
        ):
            result = preparer._load_full_context(
                content={},
                source_content={},
                context=context,
                current_item=None,
            )

        assert "severity" in result
        assert result["severity"] == "high"

    def test_no_dependency_configs_no_promotion(self):
        """When dependency_configs is None, no promotion happens (no crash)."""
        from unittest.mock import patch

        from agent_actions.processing.prepared_task import PreparationContext
        from agent_actions.processing.task_preparer import TaskPreparer

        preparer = TaskPreparer()

        mock_field_context = {
            "assess_severity": {"severity": "high"},
        }

        context = PreparationContext(
            agent_config={"context_scope": {}},
            agent_name="draft_response",
            dependency_configs=None,
        )

        with patch(
            "agent_actions.prompt.context.scope_builder.build_field_context_with_history",
            return_value=mock_field_context,
        ):
            result = preparer._load_full_context(
                content={},
                source_content={},
                context=context,
                current_item=None,
            )

        # No promotion, but no crash
        assert "severity" not in result
        assert result["assess_severity"] == {"severity": "high"}


class TestHelpersIntegration:
    """Tests for integration with processing/helpers.py."""

    def test_evaluate_guard_condition_delegates_to_evaluator(self):
        """evaluate_guard_condition uses GuardEvaluator internally."""
        from agent_actions.processing.helpers import evaluate_guard_condition

        # No guard config should pass
        should_execute, behavior = evaluate_guard_condition({}, {"field": "value"})
        assert should_execute is True
        assert behavior is None

    def test_should_skip_guard_delegates_to_evaluator(self):
        """_should_skip_guard uses GuardEvaluator internally."""
        from agent_actions.processing.helpers import _should_skip_guard

        # No guard config should not skip
        result = _should_skip_guard({}, {"field": "value"})
        assert result is False

    def test_should_filter_guard_delegates_to_evaluator(self):
        """_should_filter_guard uses GuardEvaluator internally."""
        from agent_actions.processing.helpers import _should_filter_guard

        # No guard config should not filter
        result = _should_filter_guard({}, {"field": "value"})
        assert result is False
