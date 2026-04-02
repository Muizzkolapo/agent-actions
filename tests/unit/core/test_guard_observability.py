"""Tests for guard filter observability: guard_stats, all-filtered warning, warn mode."""

import logging

import pytest

from agent_actions.guards import GuardBehavior, GuardConfig
from agent_actions.input.preprocessing.filtering.evaluator import GuardResult
from agent_actions.logging.events.data_pipeline_events import ResultCollectionCompleteEvent
from agent_actions.logging.events.handlers.run_results import ActionResult, RunResultsCollector
from agent_actions.logging.events.workflow_events import (
    ActionCompleteEvent,
    ActionStartEvent,
    WorkflowStartEvent,
)
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingResult, ProcessingStatus

# ---------------------------------------------------------------------------
# 1. GuardBehavior.WARN enum
# ---------------------------------------------------------------------------


class TestGuardBehaviorWarn:
    """Tests for the WARN enum value in GuardBehavior."""

    def test_warn_value_exists(self):
        assert GuardBehavior.WARN == "warn"
        assert GuardBehavior("warn") == GuardBehavior.WARN

    def test_guard_config_from_dict_with_warn(self):
        config = GuardConfig.from_dict({"condition": 'status == "active"', "on_false": "warn"})
        assert config.on_false == GuardBehavior.WARN

    def test_guard_config_constructor_with_warn_string(self):
        config = GuardConfig(condition='x == "y"', on_false="warn")
        assert config.on_false == GuardBehavior.WARN


# ---------------------------------------------------------------------------
# 2. ActionResult.guard_stats serialization
# ---------------------------------------------------------------------------


class TestActionResultGuardStats:
    """Tests for guard_stats field on ActionResult."""

    def test_to_dict_omits_guard_stats_when_none(self):
        result = ActionResult(
            unique_id="wf.action",
            action_name="action",
            action_index=0,
            status="success",
        )
        d = result.to_dict()
        assert "guard_stats" not in d

    def test_to_dict_includes_guard_stats_when_set(self):
        result = ActionResult(
            unique_id="wf.action",
            action_name="action",
            action_index=0,
            status="success",
            guard_stats={
                "condition": "compliance_passed == true",
                "passed": 0,
                "filtered": 8,
                "on_false": "filter",
            },
        )
        d = result.to_dict()
        assert d["guard_stats"] == {
            "condition": "compliance_passed == true",
            "passed": 0,
            "filtered": 8,
            "on_false": "filter",
        }


# ---------------------------------------------------------------------------
# 3. RunResultsCollector populates guard_stats from ResultCollectionCompleteEvent
# ---------------------------------------------------------------------------


class TestRunResultsCollectorGuardStats:
    """Tests for RunResultsCollector handling ResultCollectionCompleteEvent."""

    @pytest.fixture
    def collector(self, tmp_path):
        return RunResultsCollector(output_dir=tmp_path / "out", workflow_name="test_wf")

    def test_accepts_result_collection_complete(self, collector):
        event = ResultCollectionCompleteEvent(action_name="a")
        assert collector.accepts(event)

    def test_guard_stats_populated_on_filter(self, collector):
        collector.handle(WorkflowStartEvent(workflow_name="test_wf", action_count=1))
        collector.handle(ActionStartEvent(action_name="optimize_seo", action_index=0))
        collector.handle(ActionCompleteEvent(action_name="optimize_seo", action_index=0))

        collector.handle(
            ResultCollectionCompleteEvent(
                action_name="optimize_seo",
                total_success=0,
                total_filtered=8,
                guard_condition="compliance_passed == true",
                guard_on_false="filter",
            )
        )

        result = collector._results["optimize_seo"]
        assert result.guard_stats is not None
        assert result.guard_stats["condition"] == "compliance_passed == true"
        assert result.guard_stats["passed"] == 0
        assert result.guard_stats["filtered"] == 8
        assert result.guard_stats["on_false"] == "filter"

    def test_guard_stats_not_set_without_guard(self, collector):
        collector.handle(WorkflowStartEvent(workflow_name="test_wf", action_count=1))
        collector.handle(ActionStartEvent(action_name="no_guard", action_index=0))
        collector.handle(ActionCompleteEvent(action_name="no_guard", action_index=0))

        collector.handle(
            ResultCollectionCompleteEvent(
                action_name="no_guard",
                total_success=5,
                total_filtered=0,
            )
        )

        result = collector._results["no_guard"]
        assert result.guard_stats is None

    def test_guard_stats_partial_filter(self, collector):
        collector.handle(WorkflowStartEvent(workflow_name="test_wf", action_count=1))
        collector.handle(ActionStartEvent(action_name="partial", action_index=0))
        collector.handle(ActionCompleteEvent(action_name="partial", action_index=0))

        collector.handle(
            ResultCollectionCompleteEvent(
                action_name="partial",
                total_success=5,
                total_filtered=3,
                guard_condition="score > 50",
                guard_on_false="filter",
            )
        )

        result = collector._results["partial"]
        assert result.guard_stats is not None
        assert result.guard_stats["passed"] == 5
        assert result.guard_stats["filtered"] == 3

    def test_guard_stats_passed_excludes_skipped(self, collector):
        """Skipped records (on_false=skip tombstones) must not count as passed."""
        collector.handle(WorkflowStartEvent(workflow_name="test_wf", action_count=1))
        collector.handle(ActionStartEvent(action_name="mixed", action_index=0))
        collector.handle(ActionCompleteEvent(action_name="mixed", action_index=0))

        collector.handle(
            ResultCollectionCompleteEvent(
                action_name="mixed",
                total_success=3,
                total_skipped=2,
                total_filtered=5,
                guard_condition="status == active",
                guard_on_false="filter",
            )
        )

        result = collector._results["mixed"]
        assert result.guard_stats is not None
        assert result.guard_stats["passed"] == 3  # only success, not skipped


# ---------------------------------------------------------------------------
# 4. All-filtered warning log
# ---------------------------------------------------------------------------


class TestAllFilteredWarning:
    """Tests for warning log when guard filters all records."""

    @staticmethod
    def _make_filtered_results(n: int) -> list[ProcessingResult]:
        return [ProcessingResult(status=ProcessingStatus.FILTERED, data=None) for _ in range(n)]

    @staticmethod
    def _make_mixed_results(n_success: int, n_filtered: int) -> list[ProcessingResult]:
        results = [
            ProcessingResult(status=ProcessingStatus.SUCCESS, data=[{"content": "ok"}])
            for _ in range(n_success)
        ]
        results.extend(
            ProcessingResult(status=ProcessingStatus.FILTERED, data=None) for _ in range(n_filtered)
        )
        return results

    def test_warning_emitted_when_all_filtered(self):
        results = self._make_filtered_results(8)
        agent_config = {
            "guard": {
                "clause": "compliance_passed == true",
                "behavior": "filter",
            }
        }
        target_logger = logging.getLogger("agent_actions.processing.result_collector")
        captured: list[logging.LogRecord] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        handler = _CaptureHandler(level=logging.WARNING)
        target_logger.addHandler(handler)
        try:
            ResultCollector.collect_results(
                results, agent_config, "optimize_seo", is_first_stage=False
            )
        finally:
            target_logger.removeHandler(handler)

        assert any("All 8 records filtered by guard" in record.getMessage() for record in captured)

    def test_no_warning_on_partial_filter(self, caplog):
        results = self._make_mixed_results(5, 3)
        agent_config = {
            "guard": {
                "clause": "score > 50",
                "behavior": "filter",
            }
        }
        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.result_collector"):
            ResultCollector.collect_results(
                results, agent_config, "score_check", is_first_stage=False
            )

        assert not any(
            "All" in record.message and "records filtered by guard" in record.message
            for record in caplog.records
        )

    def test_no_warning_when_no_filter(self, caplog):
        results = [
            ProcessingResult(status=ProcessingStatus.SUCCESS, data=[{"content": "ok"}])
            for _ in range(5)
        ]
        agent_config = {}
        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.result_collector"):
            ResultCollector.collect_results(results, agent_config, "no_guard", is_first_stage=False)

        assert not any("records filtered by guard" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# 5. GuardResult.warned() and warn behavior in evaluator
# ---------------------------------------------------------------------------


class TestGuardResultWarnMode:
    """Tests for warn mode in guard evaluation."""

    def test_warned_factory(self):
        result = GuardResult.warned()
        assert result.should_execute is True
        assert result.behavior == "warn"
        assert result.matched is False

    def test_from_filter_result_warn_not_matched(self):
        from agent_actions.input.preprocessing.filtering.guard_filter import FilterResult

        filter_result = FilterResult(success=True, matched=False)
        guard_result = GuardResult.from_filter_result(
            filter_result, behavior="warn", passthrough_on_error=True
        )
        assert guard_result.should_execute is True
        assert guard_result.behavior == "warn"

    def test_from_filter_result_warn_matched(self):
        from agent_actions.input.preprocessing.filtering.guard_filter import FilterResult

        filter_result = FilterResult(success=True, matched=True)
        guard_result = GuardResult.from_filter_result(
            filter_result, behavior="warn", passthrough_on_error=True
        )
        assert guard_result.should_execute is True
        assert guard_result.behavior is None  # passed — no warn needed

    def test_from_filter_result_warn_on_error(self):
        from agent_actions.input.preprocessing.filtering.guard_filter import FilterResult

        filter_result = FilterResult(success=False, matched=False, error="eval error")
        guard_result = GuardResult.from_filter_result(
            filter_result, behavior="warn", passthrough_on_error=False
        )
        assert guard_result.should_execute is True
        assert guard_result.behavior == "warn"


# ---------------------------------------------------------------------------
# 6. TaskPreparer warn-mode per-record logging
# ---------------------------------------------------------------------------


class TestTaskPreparerWarnLogging:
    """Tests for per-record warning log in task_preparer when guard behavior is warn."""

    def test_warn_mode_logs_per_record_warning(self):
        from unittest.mock import MagicMock, patch

        from agent_actions.processing.prepared_task import PreparationContext
        from agent_actions.processing.task_preparer import TaskPreparer

        preparer = TaskPreparer()
        context = MagicMock(spec=PreparationContext)
        context.agent_name = "test_action"
        context.agent_config = {
            "guard": {
                "clause": "quality_score > 0.5",
                "scope": "item",
                "behavior": "warn",
            },
        }
        context.is_first_stage = False
        context.source_data = None
        context.agent_indices = None
        context.dependency_configs = None
        context.workflow_metadata = None
        context.version_context = None
        context.file_path = None
        context.output_directory = None
        context.storage_backend = None
        context.current_item = None
        context.record_index = 0

        item = {"content": {"quality_score": 0.1}, "source_guid": "sg-1"}

        warned_result = GuardResult.warned()

        target_logger = logging.getLogger("agent_actions.processing.task_preparer")
        captured: list[logging.LogRecord] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        handler = _CaptureHandler(level=logging.WARNING)
        target_logger.addHandler(handler)
        try:
            with (
                patch.object(preparer, "_normalize_input", return_value=(item, "sg-1", item)),
                patch.object(preparer, "_is_upstream_unprocessed", return_value=False),
                patch.object(preparer, "_load_full_context", return_value={"quality_score": 0.1}),
                patch.object(preparer, "_evaluate_guard", return_value=warned_result),
                patch.object(
                    preparer,
                    "_render_prompt",
                    return_value=MagicMock(
                        formatted_prompt="p",
                        llm_context={},
                        passthrough_fields={},
                        prompt_context={},
                    ),
                ),
            ):
                result = preparer.prepare(item, context)
        finally:
            target_logger.removeHandler(handler)

        # Record should be processed normally (not filtered/skipped)
        assert result.guard_status.value == "passed"

        # Warning should mention the guard condition and warn mode
        assert any(
            "passing through (warn mode)" in r.getMessage()
            and "quality_score > 0.5" in r.getMessage()
            for r in captured
        )
