"""Phase 1 observability tests — U-2.G, U-2.H, U-2.E.

Tests that WARNING logs and RuntimeError guards exist for:
- _mark_prep_failed with missing target_id (U-2.G)
- passthrough_on_error swallowing exceptions (U-2.H)
- prefilter_by_guard original_data/data length mismatch (U-2.E)
"""

import logging
from unittest.mock import MagicMock

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.input.preprocessing.filtering.guard_filter import GuardFilter
from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.record.state import RecordState
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

_PREPARATOR_LOGGER = "agent_actions.llm.batch.processing.preparator"
_EVALUATOR_LOGGER = "agent_actions.input.preprocessing.filtering.evaluator"


@pytest.fixture(autouse=True)
def _enable_log_propagation():
    """Ensure agent_actions loggers propagate to root so caplog captures them.

    The agent_actions root logger has propagate=False (set by LoggingBridgeHandler),
    so caplog (which hooks the Python root logger) can't see child log records.
    Temporarily enable propagation for the duration of each test.
    """
    aa_logger = logging.getLogger("agent_actions")
    orig = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = orig


class TestPrepFailedLogging:
    """U-2.G: _mark_prep_failed must warn when target_id is missing."""

    def test_prep_failed_without_target_id_logs_warning(self, caplog):
        """When prep fails and record has no target_id, WARNING must appear in logs."""
        preparator = BatchTaskPreparator()
        record_without_target = {"content": {"text": "no target_id here"}}
        context_map = {}

        with caplog.at_level(logging.WARNING, logger=_PREPARATOR_LOGGER):
            preparator._mark_prep_failed(
                record_without_target,
                context_map,
                "test_agent",
                ValueError("test error"),
            )

        assert any("target_id" in r.message and r.levelname == "WARNING" for r in caplog.records), (
            "Missing WARNING about absent target_id on prep failure"
        )

    def test_prep_failed_empty_string_target_id_logs_warning(self, caplog):
        """Empty-string target_id is falsy — must warn same as absent."""
        preparator = BatchTaskPreparator()
        record = {"target_id": "", "content": {"text": "empty target"}}
        context_map = {}

        with caplog.at_level(logging.WARNING, logger=_PREPARATOR_LOGGER):
            preparator._mark_prep_failed(
                record,
                context_map,
                "test_agent",
                ValueError("test error"),
            )

        assert any("target_id" in r.message and r.levelname == "WARNING" for r in caplog.records), (
            "Missing WARNING for empty-string target_id"
        )

    def test_prep_failed_with_target_id_no_extra_warning(self, caplog):
        """When prep fails and target_id exists, no warning about missing target_id."""
        preparator = BatchTaskPreparator()
        record = {"target_id": "t-001", "content": {"text": "has target"}}
        context_map = {"t-001": record.copy()}
        context_map["t-001"]["_state"] = RecordState.ACTIVE.value
        BatchContextMetadata.set_filter_status(context_map["t-001"], FilterStatus.INCLUDED)

        with caplog.at_level(logging.WARNING, logger=_PREPARATOR_LOGGER):
            preparator._mark_prep_failed(
                record,
                context_map,
                "test_agent",
                ValueError("test error"),
            )

        target_id_warnings = [
            r
            for r in caplog.records
            if "target_id" in r.message and "untrackable" in r.message and r.levelname == "WARNING"
        ]
        assert len(target_id_warnings) == 0, (
            "Should NOT warn about missing target_id when target_id is present"
        )


class TestPassthroughOnErrorLogging:
    """U-2.H: passthrough_on_error must log WARNING when exception is swallowed."""

    def test_passthrough_on_error_logs_warning_on_exception(self, caplog):
        """When guard raises and passthrough_on_error=True, WARNING logged with context."""
        mock_filter = MagicMock(spec=GuardFilter)
        mock_filter.filter_item.side_effect = ValueError("bad expression")
        evaluator = GuardEvaluator(guard_filter=mock_filter)

        guard_config = {
            "clause": "some_field == true",
            "behavior": "filter",
            "passthrough_on_error": True,
        }

        with caplog.at_level(
            logging.WARNING,
            logger=_EVALUATOR_LOGGER,
        ):
            result = evaluator.evaluate(
                item={"field": "value"},
                guard_config=guard_config,
            )

        # Must still pass (passthrough_on_error behavior unchanged)
        assert result.should_execute is True

        # Must log WARNING mentioning passthrough_on_error
        passthrough_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "passthrough_on_error" in r.message
        ]
        assert len(passthrough_warnings) == 1, (
            "Must log exactly one WARNING mentioning passthrough_on_error when exception is swallowed"
        )

    def test_passthrough_on_error_default_true_logs_warning(self, caplog):
        """When passthrough_on_error key is omitted, default=True triggers the warning."""
        mock_filter = MagicMock(spec=GuardFilter)
        mock_filter.filter_item.side_effect = ValueError("bad expression")
        evaluator = GuardEvaluator(guard_filter=mock_filter)

        guard_config = {
            "clause": "some_field == true",
            "behavior": "filter",
            # passthrough_on_error omitted — defaults to True
        }

        with caplog.at_level(logging.WARNING, logger=_EVALUATOR_LOGGER):
            result = evaluator.evaluate(
                item={"field": "value"},
                guard_config=guard_config,
            )

        assert result.should_execute is True
        passthrough_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "passthrough_on_error" in r.message
        ]
        assert len(passthrough_warnings) == 1, (
            "Default passthrough_on_error=True must trigger the passthrough warning"
        )

    def test_passthrough_on_error_false_no_passthrough_warning(self, caplog):
        """When passthrough_on_error=False, no passthrough-specific warning."""
        mock_filter = MagicMock(spec=GuardFilter)
        mock_filter.filter_item.side_effect = ValueError("bad expression")
        evaluator = GuardEvaluator(guard_filter=mock_filter)

        guard_config = {
            "clause": "some_field == true",
            "behavior": "filter",
            "passthrough_on_error": False,
        }

        with caplog.at_level(
            logging.WARNING,
            logger=_EVALUATOR_LOGGER,
        ):
            result = evaluator.evaluate(
                item={"field": "value"},
                guard_config=guard_config,
            )

        assert result.should_execute is False

        passthrough_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "passthrough_on_error" in r.message
        ]
        assert len(passthrough_warnings) == 0, (
            "Should NOT log passthrough-specific warning when passthrough_on_error=False"
        )


class TestPrefilterLengthGuard:
    """U-2.E: prefilter_by_guard must raise on original_data/data length mismatch."""

    def test_original_data_length_mismatch_raises(self):
        """If original_data has different length than data, RuntimeError raised."""
        data = [{"content": {"x": 1}}, {"content": {"x": 2}}, {"content": {"x": 3}}]
        original_data = [{"content": {"x": 1}}, {"content": {"x": 2}}]  # only 2 for 3

        with pytest.raises(RuntimeError, match="prefilter_by_guard.*2.*3"):
            prefilter_by_guard(data, {}, "test_agent", original_data=original_data)

    def test_matching_lengths_no_error(self):
        """When original_data matches data length, no error."""
        data = [{"content": {"x": 1}}, {"content": {"x": 2}}]
        original_data = [{"content": {"x": 1, "extra": "a"}}, {"content": {"x": 2, "extra": "b"}}]

        passing, skipped, original_passing = prefilter_by_guard(
            data, {}, "test_agent", original_data=original_data
        )
        assert len(passing) == 2
        assert original_passing == original_data
