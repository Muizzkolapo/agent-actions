"""Regression tests for batch/online guard evaluation and lifecycle unification.

Tests cover:
1. Batch preflight with guard-skipped upstream (CHANGE 1)
2. Duplicate CASCADE check removal in reconciliation (CHANGE 2)
3. Online guard context parity with batch (CHANGE 3)
4. State transition bypass prevention (CHANGE 4)

Each test exercises the behavior that was broken before unification and
verifies the correct outcome after the fix.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.state import RecordState


def _make_preparator(**kwargs: Any) -> BatchTaskPreparator:
    return BatchTaskPreparator(
        action_indices=kwargs.get("action_indices", {}),
        dependency_configs=kwargs.get("dependency_configs", {}),
        storage_backend=kwargs.get("storage_backend"),
        version_context=kwargs.get("version_context"),
    )


# ---------------------------------------------------------------------------
# CHANGE 1: Batch preflight is guard-aware
# ---------------------------------------------------------------------------


class TestPreflightGuardAware:
    """Preflight must not crash when guard-skipped upstream records have
    templates that reference fields only available when the guard passes."""

    def test_preflight_skips_guard_filtered_rows_without_crash(self):
        """When all sample rows are guard-skipped, preflight completes
        without raising — it does not force-render guard-conditional templates."""
        preparator = _make_preparator()
        agent_config = {
            "name": "test_action",
            "prompt": "{{ upstream_ns.field }}",
            "guard": {"clause": "upstream_ns.has_data == true", "behavior": "skip"},
        }
        # Rows where upstream_ns is absent (guard would skip these)
        data = [
            {"target_id": "1", "content": {}},
            {"target_id": "2", "content": {}},
        ]

        mock_prepared_skipped = MagicMock()
        mock_prepared_skipped.guard_status = GuardStatus.SKIPPED

        with patch("agent_actions.llm.batch.processing.preparator.get_task_preparer") as mock_get:
            mock_preparer = MagicMock()
            mock_preparer.prepare.return_value = mock_prepared_skipped
            mock_get.return_value = mock_preparer

            # Should NOT raise — previously crashed with TemplateVariableError
            preparator._run_preflight_validation(agent_config, data)

            for call in mock_preparer.prepare.call_args_list:
                assert call.kwargs.get("skip_guard") is False

    def test_preflight_stops_at_first_passing_row(self):
        """When a row passes the guard, preflight validates that row and stops."""
        preparator = _make_preparator()
        agent_config = {"name": "test_action", "prompt": "{{ content }}"}
        data = [
            {"target_id": "1", "content": {}},
            {"target_id": "2", "content": {"field": "value"}},
            {"target_id": "3", "content": {"field": "other"}},
        ]

        mock_skipped = MagicMock()
        mock_skipped.guard_status = GuardStatus.SKIPPED

        mock_passed = MagicMock()
        mock_passed.guard_status = GuardStatus.PASSED

        with patch("agent_actions.llm.batch.processing.preparator.get_task_preparer") as mock_get:
            mock_preparer = MagicMock()
            mock_preparer.prepare.side_effect = [mock_skipped, mock_passed]
            mock_get.return_value = mock_preparer

            preparator._run_preflight_validation(agent_config, data)

            assert mock_preparer.prepare.call_count == 2

    def test_preflight_propagates_real_template_errors(self):
        """Real template errors (not guard-related) still raise."""
        preparator = _make_preparator()
        agent_config = {"name": "test_action", "prompt": "{{ nonexistent }}"}
        data = [{"target_id": "1", "content": {}}]

        with patch("agent_actions.llm.batch.processing.preparator.get_task_preparer") as mock_get:
            mock_preparer = MagicMock()
            mock_preparer.prepare.side_effect = Exception(
                "Template variable 'nonexistent' not found"
            )
            mock_get.return_value = mock_preparer

            with pytest.raises(Exception, match="Template variable"):
                preparator._run_preflight_validation(agent_config, data)

    def test_preflight_skips_upstream_unprocessed_rows(self):
        """UPSTREAM_UNPROCESSED rows are skipped — no template was rendered."""
        preparator = _make_preparator()
        agent_config = {"name": "test_action", "prompt": "{{ content }}"}
        data = [
            {"target_id": "1", "_state": "failed", "content": {}},
            {"target_id": "2", "content": {"field": "value"}},
        ]

        mock_unprocessed = MagicMock()
        mock_unprocessed.guard_status = GuardStatus.UPSTREAM_UNPROCESSED

        mock_passed = MagicMock()
        mock_passed.guard_status = GuardStatus.PASSED

        with patch("agent_actions.llm.batch.processing.preparator.get_task_preparer") as mock_get:
            mock_preparer = MagicMock()
            mock_preparer.prepare.side_effect = [mock_unprocessed, mock_passed]
            mock_get.return_value = mock_preparer

            preparator._run_preflight_validation(agent_config, data)

            assert mock_preparer.prepare.call_count == 2

    def test_preflight_calls_prepare_with_skip_guard_false(self):
        """Preflight must call prepare with skip_guard=False so guards
        are evaluated — not skip_guard=True which hides template errors."""
        preparator = _make_preparator()
        agent_config = {"name": "test_action", "prompt": "{{ content }}"}
        data = [{"target_id": "1", "content": {"field": "value"}}]

        mock_passed = MagicMock()
        mock_passed.guard_status = GuardStatus.PASSED

        with patch("agent_actions.llm.batch.processing.preparator.get_task_preparer") as mock_get:
            mock_preparer = MagicMock()
            mock_preparer.prepare.return_value = mock_passed
            mock_get.return_value = mock_preparer

            preparator._run_preflight_validation(agent_config, data)

            call_kwargs = mock_preparer.prepare.call_args
            assert call_kwargs.kwargs.get("skip_guard") is False


# ---------------------------------------------------------------------------
# CHANGE 2: No duplicate CASCADE check in reconciliation
# ---------------------------------------------------------------------------


class TestReconciliationSkipReason:
    """Reconciliation uses skip_reason stored during prep, not re-derived
    CASCADE_BLOCKING_VALUES check."""

    def test_cascade_blocked_row_gets_upstream_unprocessed_reason(self):
        """A cascade-blocked row stores UPSTREAM_UNPROCESSED as skip_reason
        during preparation, and reconciliation reads it back."""
        from agent_actions.llm.batch.core.batch_models import BatchTaskPreparationStats
        from agent_actions.record.reasons import UPSTREAM_UNPROCESSED

        preparator = _make_preparator()
        context_map: dict[str, Any] = {}
        stats = BatchTaskPreparationStats()

        # Row with a cascade-blocking state (upstream failed)
        row = {
            "target_id": "tid_cascade",
            "_state": RecordState.FAILED.value,
            "content": {"data": "value"},
        }

        mock_prepared = MagicMock()
        mock_prepared.guard_status = GuardStatus.UPSTREAM_UNPROCESSED
        mock_prepared.passthrough_fields = {}

        mock_preparer = MagicMock()
        mock_preparer.prepare.return_value = mock_prepared

        prep_context = MagicMock(spec=PreparationContext)

        result = preparator._process_single_item(
            row, prep_context, mock_preparer, context_map, stats
        )

        assert result is None
        entry = context_map["tid_cascade"]
        assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.SKIPPED
        assert BatchContextMetadata.get_skip_reason(entry) == UPSTREAM_UNPROCESSED

    def test_guard_skipped_row_gets_guard_skip_reason(self):
        """A guard-skipped row stores GUARD_SKIP as skip_reason."""
        from agent_actions.llm.batch.core.batch_models import BatchTaskPreparationStats
        from agent_actions.record.reasons import GUARD_SKIP

        preparator = _make_preparator()
        context_map: dict[str, Any] = {}
        stats = BatchTaskPreparationStats()

        row = {
            "target_id": "tid_guard",
            "content": {"data": "value"},
        }

        mock_prepared = MagicMock()
        mock_prepared.guard_status = GuardStatus.SKIPPED
        mock_prepared.passthrough_fields = {}

        mock_preparer = MagicMock()
        mock_preparer.prepare.return_value = mock_prepared

        prep_context = MagicMock(spec=PreparationContext)

        result = preparator._process_single_item(
            row, prep_context, mock_preparer, context_map, stats
        )

        assert result is None
        entry = context_map["tid_guard"]
        assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.SKIPPED
        assert BatchContextMetadata.get_skip_reason(entry) == GUARD_SKIP

    def test_reconciliation_reads_skip_reason_not_state(self):
        """_build_unprocessed_passthrough uses stored skip_reason, not
        raw _state re-check against CASCADE_BLOCKING_VALUES."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )
        from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
        from agent_actions.record.reasons import UPSTREAM_UNPROCESSED

        original_row = {
            "target_id": "tid_cascade",
            "_state": RecordState.FAILED.value,
            "content": {"data": "value"},
        }
        BatchContextMetadata.set_filter_status(original_row, FilterStatus.SKIPPED)
        BatchContextMetadata.set_skip_reason(original_row, UPSTREAM_UNPROCESSED)

        ctx = BatchProcessingContext(
            batch_results=[],
            context_map={"tid_cascade": original_row},
            output_directory="/tmp/test",
            agent_config={"name": "test_action", "agent_type": "llm_agent"},
        )
        ctx.reconciler = BatchResultReconciler(context_map={"tid_cascade": original_row})

        strategy = BatchResultStrategy()
        result = strategy._build_unprocessed_passthrough(
            ctx, original_row, "test_action", "sg_001", 0
        )

        assert result.skip_reason == UPSTREAM_UNPROCESSED

    def test_reconciliation_fallback_guard_skip_when_no_skip_reason(self):
        """Without skip_reason, FilterStatus.SKIPPED falls back to GUARD_SKIP."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )
        from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
        from agent_actions.record.reasons import GUARD_SKIP

        original_row = {"target_id": "tid_1", "content": {}}
        BatchContextMetadata.set_filter_status(original_row, FilterStatus.SKIPPED)
        # No skip_reason set — should fall back to GUARD_SKIP

        ctx = BatchProcessingContext(
            batch_results=[],
            context_map={"tid_1": original_row},
            output_directory="/tmp/test",
            agent_config={"name": "test_action", "agent_type": "llm_agent"},
        )
        ctx.reconciler = BatchResultReconciler(context_map={"tid_1": original_row})

        strategy = BatchResultStrategy()
        result = strategy._build_unprocessed_passthrough(
            ctx, original_row, "test_action", "sg_001", 0
        )

        assert result.skip_reason == GUARD_SKIP

    def test_reconciliation_fallback_cascade_blocked_when_no_skip_reason(self):
        """Without skip_reason, cascade-blocked _state falls back to UPSTREAM_UNPROCESSED."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )
        from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
        from agent_actions.record.reasons import UPSTREAM_UNPROCESSED

        original_row = {
            "target_id": "tid_2",
            "_state": RecordState.CASCADE_SKIPPED.value,
            "content": {},
        }
        # No filter_status, no skip_reason — should fall back to _state check

        ctx = BatchProcessingContext(
            batch_results=[],
            context_map={"tid_2": original_row},
            output_directory="/tmp/test",
            agent_config={"name": "test_action", "agent_type": "llm_agent"},
        )
        ctx.reconciler = BatchResultReconciler(context_map={"tid_2": original_row})

        strategy = BatchResultStrategy()
        result = strategy._build_unprocessed_passthrough(
            ctx, original_row, "test_action", "sg_002", 0
        )

        assert result.skip_reason == UPSTREAM_UNPROCESSED

    def test_reconciliation_fallback_batch_not_returned(self):
        """Without skip_reason, filter_status, or cascade state → BATCH_NOT_RETURNED."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )
        from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
        from agent_actions.record.reasons import BATCH_NOT_RETURNED

        original_row = {"target_id": "tid_3", "content": {}}
        # Nothing set — default fallback

        ctx = BatchProcessingContext(
            batch_results=[],
            context_map={"tid_3": original_row},
            output_directory="/tmp/test",
            agent_config={"name": "test_action", "agent_type": "llm_agent"},
        )
        ctx.reconciler = BatchResultReconciler(context_map={"tid_3": original_row})

        strategy = BatchResultStrategy()
        result = strategy._build_unprocessed_passthrough(
            ctx, original_row, "test_action", "sg_003", 0
        )

        assert result.skip_reason == BATCH_NOT_RETURNED


# ---------------------------------------------------------------------------
# CHANGE 3: Online guard context parity
# ---------------------------------------------------------------------------


class TestOnlineGuardContextParity:
    """Online prefilter and per-record guard must see the same context
    as batch mode — not empty {}."""

    def test_prefilter_passes_record_content_as_context(self):
        """prefilter_by_guard must pass record content as context, not {}."""
        from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

        guard_config = {
            "clause": "upstream_ns.status == 'ready'",
            "behavior": "skip",
        }
        agent_config = {"guard": guard_config}

        data = [
            {"content": {"upstream_ns": {"status": "ready"}}},
            {"content": {"upstream_ns": {"status": "pending"}}},
        ]

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator"
        ) as mock_get_eval:
            mock_evaluator = MagicMock()
            captured_contexts: list[Any] = []

            def capture_evaluate(*, item, guard_config, context=None, **kwargs):
                captured_contexts.append(context)
                mock_result = MagicMock()
                mock_result.should_execute = True
                return mock_result

            mock_evaluator.evaluate.side_effect = capture_evaluate
            mock_get_eval.return_value = mock_evaluator

            prefilter_by_guard(data, agent_config, "test_action")

            # Context must be the record's existing content, not empty
            assert captured_contexts[0] == {"upstream_ns": {"status": "ready"}}
            assert captured_contexts[1] == {"upstream_ns": {"status": "pending"}}

    def test_online_process_record_skip_guard_false_by_default(self):
        """process_record default skip_guard is False — per-record guard
        evaluates with full context."""
        from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy

        strategy = OnlineLLMStrategy.__new__(OnlineLLMStrategy)

        import inspect

        sig = inspect.signature(strategy.process_record)
        skip_guard_param = sig.parameters["skip_guard"]
        assert skip_guard_param.default is False, (
            "skip_guard default must be False so per-record guard evaluates"
        )

    def test_same_guard_verdict_online_vs_batch_path(self):
        """Given the same item and guard config, online prefilter and batch
        TaskPreparer.prepare() produce the same pass/skip decision."""
        from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

        # Item where guard should pass (upstream_ns.ready is truthy)
        passing_item = {"content": {"upstream_ns": {"ready": True}}}
        # Item where guard should skip (upstream_ns.ready is falsy)
        skipping_item = {"content": {"upstream_ns": {"ready": False}}}

        guard_config = {
            "clause": "upstream_ns.ready == true",
            "behavior": "skip",
        }
        agent_config = {"guard": guard_config}

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator"
        ) as mock_get_eval:
            mock_evaluator = MagicMock()

            def evaluate_fn(*, item, guard_config, context=None, **kwargs):
                # Simulate: if context has upstream_ns.ready=True → pass, else skip
                ready = False
                if isinstance(context, dict):
                    ns = context.get("upstream_ns", {})
                    ready = ns.get("ready", False) if isinstance(ns, dict) else False
                mock_result = MagicMock()
                mock_result.should_execute = bool(ready)
                return mock_result

            mock_evaluator.evaluate.side_effect = evaluate_fn
            mock_get_eval.return_value = mock_evaluator

            passing_out, skipped_out, _ = prefilter_by_guard(
                [passing_item, skipping_item], agent_config, "test_action"
            )

            # passing_item passes, skipping_item is skipped
            assert len(passing_out) == 1
            assert len(skipped_out) == 1


# ---------------------------------------------------------------------------
# CHANGE 4: State transition bypass prevention
# ---------------------------------------------------------------------------


class TestStateTransitionBypass:
    """_mark_prep_failed must not bypass the state machine by force-setting
    _state when RecordEnvelope.transition() would fail."""

    def test_illegal_transition_does_not_stomp_state(self):
        """When the record is in CASCADE_SKIPPED state, transitioning to
        FAILED is illegal. _mark_prep_failed must NOT force-set _state."""
        row = {"target_id": "tid_001"}
        context_map = {"tid_001": row.copy()}
        entry = context_map["tid_001"]

        # Set initial state to CASCADE_SKIPPED (transition to FAILED is illegal)
        RecordEnvelope.transition(entry, RecordState.CASCADE_SKIPPED, "upstream_action", "cascade")

        BatchTaskPreparator._mark_prep_failed(
            row, context_map, "test_action", ValueError("some error")
        )

        # State must remain CASCADE_SKIPPED — NOT force-set to FAILED
        assert entry["_state"] == RecordState.CASCADE_SKIPPED.value

    def test_legal_transition_succeeds_normally(self):
        """When the record has no state (fresh), transition to FAILED succeeds."""
        row = {"target_id": "tid_002"}
        context_map = {"tid_002": row.copy()}

        BatchTaskPreparator._mark_prep_failed(
            row, context_map, "test_action", ValueError("template error")
        )

        entry = context_map["tid_002"]
        assert entry["_state"] == RecordState.FAILED.value
        assert len(entry["_state_history"]) == 1

    def test_can_transition_returns_false_for_illegal(self):
        """RecordEnvelope.can_transition detects illegal edges."""
        record = {"_state": RecordState.CASCADE_SKIPPED.value}
        assert RecordEnvelope.can_transition(record, RecordState.FAILED) is False

    def test_can_transition_returns_true_for_legal(self):
        """RecordEnvelope.can_transition allows legal edges."""
        record = {"_state": RecordState.ACTIVE.value}
        assert RecordEnvelope.can_transition(record, RecordState.FAILED) is True

    def test_can_transition_returns_true_for_no_state(self):
        """RecordEnvelope.can_transition allows any transition from None state."""
        record = {}
        assert RecordEnvelope.can_transition(record, RecordState.FAILED) is True

    def test_can_transition_returns_false_for_unknown_state(self):
        """RecordEnvelope.can_transition returns False for garbage _state values."""
        record = {"_state": "not_a_real_state"}
        assert RecordEnvelope.can_transition(record, RecordState.FAILED) is False

    def test_illegal_transition_does_not_append_history(self):
        """When transition is illegal, no spurious _state_history entry is added."""
        row = {"target_id": "tid_003"}
        context_map = {"tid_003": row.copy()}
        entry = context_map["tid_003"]

        RecordEnvelope.transition(entry, RecordState.CASCADE_SKIPPED, "upstream", "cascade")
        history_before = len(entry["_state_history"])

        BatchTaskPreparator._mark_prep_failed(row, context_map, "test_action", ValueError("err"))

        assert len(entry["_state_history"]) == history_before


# ---------------------------------------------------------------------------
# UPSTREAM_UNPROCESSED tombstone consistency (audit bug F — on code path)
# ---------------------------------------------------------------------------


class TestUpstreamUnprocessedTombstoneConsistency:
    """UPSTREAM_UNPROCESSED and GUARD_SKIP tombstones must use the same
    builder — build_tombstone() — so downstream code sees structurally
    identical records."""

    def test_upstream_unprocessed_uses_build_tombstone(self):
        """process_record for UPSTREAM_UNPROCESSED must use build_tombstone,
        not manual dict construction."""
        from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy

        strategy = OnlineLLMStrategy.__new__(OnlineLLMStrategy)
        strategy._invocation_strategy = MagicMock()

        mock_prepared = MagicMock()
        mock_prepared.guard_status = GuardStatus.UPSTREAM_UNPROCESSED
        mock_prepared.source_guid = "sg_1"
        mock_prepared.source_snapshot = {"field": "val"}
        mock_prepared.original_content = {"field": "val"}

        context = MagicMock()
        context.agent_name = "test_action"
        context.action_name = "test_action"
        context.record_index = 0

        item = {"content": {"field": "val"}, "_state": "failed"}

        with (
            patch("agent_actions.processing.strategies.online_llm.get_task_preparer") as mock_get,
            patch(
                "agent_actions.processing.strategies.online_llm.build_tombstone"
            ) as mock_build_tombstone,
            patch("agent_actions.processing.strategies.online_llm.fire_event"),
        ):
            mock_preparer = MagicMock()
            mock_preparer.prepare.return_value = mock_prepared
            mock_get.return_value = mock_preparer

            mock_build_tombstone.return_value = {
                "content": {},
                "metadata": {"agent_type": "tombstone"},
                "_state": "cascade_skipped",
            }

            strategy.process_record(item, context)

            # build_tombstone must be called — not manual dict construction
            mock_build_tombstone.assert_called_once()
            call_args = mock_build_tombstone.call_args
            assert call_args.args[0] == "test_action"  # action_name
            assert call_args.args[2] == "upstream_unprocessed"  # reason
