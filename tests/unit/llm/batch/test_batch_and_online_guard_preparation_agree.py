"""Batch preparation and online processing evaluate guards and build context alike.

- Batch preflight runs guards (skip_guard=False) and moves past rows a guard or
  an unprocessed upstream skips.
- Online process_record evaluates the guard by default.
- Both paths build their context with ProcessingPipeline._build_pipeline_context.
"""

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_models import BatchTaskPreparationStats
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard


@pytest.fixture
def sample_records() -> list[dict[str, Any]]:
    """Multiple records for batch/list processing tests."""
    return [
        {
            "target_id": "test-001",
            "source_guid": "sg-001",
            "content": {"text": "record 1", "upstream_ns": {"status": "ready"}},
        },
        {
            "target_id": "test-002",
            "source_guid": "sg-002",
            "content": {"text": "record 2", "upstream_ns": {"status": "pending"}},
        },
        {
            "target_id": "test-003",
            "source_guid": "sg-003",
            "content": {"text": "record 3", "upstream_ns": {"status": "ready"}},
        },
    ]


@pytest.fixture
def paired_execution():
    """Run same payload through both online prefilter and batch prepare paths.

    Returns a function that accepts records and guard config, runs both paths,
    and returns (online_decisions, batch_decisions) as lists of decision strings
    for comparison.

    Both paths use a deterministic mock evaluator (hardcoded to check
    upstream_ns.status). This verifies the fixture plumbing works and that
    both paths exercise guard dispatch logic. It does NOT test real guard
    evaluation parity — that requires real evaluator integration tests.
    """

    def _run(
        records: list[dict[str, Any]],
        guard_config: dict[str, Any] | None = None,
    ) -> tuple[list[str], list[str]]:
        if not guard_config:
            # No guard — both paths pass everything
            return (
                ["passed"] * len(records),
                ["passed"] * len(records),
            )

        agent_config = {"name": "test_action", "guard": guard_config}

        # --- Online path: prefilter_by_guard ---
        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator"
        ) as mock_eval:
            mock_evaluator = MagicMock()
            online_decisions: list[str] = []

            def online_evaluate(*, item, guard_config, context=None, **kwargs):
                result = MagicMock()
                # item is get_existing_content(record) — the record's own
                # namespaces. upstream_ns is a dependency namespace, not
                # source content, so it lives here, never under context["source"].
                is_ready = False
                if isinstance(item, dict):
                    ns = item.get("upstream_ns")
                    if isinstance(ns, dict):
                        is_ready = ns.get("status") == "ready"
                result.should_execute = is_ready
                online_decisions.append("passed" if result.should_execute else "skipped")
                return result

            mock_evaluator.evaluate.side_effect = online_evaluate
            mock_eval.return_value = mock_evaluator

            prefilter_by_guard(records, agent_config, "test_action")

        # --- Batch path: TaskPreparer.prepare with skip_guard=False ---
        batch_decisions: list[str] = []
        preparator = BatchTaskPreparator(
            action_indices={},
            dependency_configs={},
        )

        mock_preparer = MagicMock()

        def batch_prepare(row, ctx, **kwargs):
            content = row.get("content", {})
            is_ready = content.get("upstream_ns", {}).get("status") == "ready"
            result = MagicMock()
            if is_ready:
                result.guard_status = GuardStatus.PASSED
                batch_decisions.append("passed")
            else:
                result.guard_status = GuardStatus.SKIPPED
                batch_decisions.append("skipped")
            result.passthrough_fields = {}
            return result

        mock_preparer.prepare.side_effect = batch_prepare

        context_map: dict[str, Any] = {}
        stats = BatchTaskPreparationStats()
        prep_context = MagicMock(spec=PreparationContext)

        for row in records:
            preparator._process_single_item(row, prep_context, mock_preparer, context_map, stats)

        return online_decisions, batch_decisions

    return _run


class TestU01BatchPreflightGuardAware:
    """Batch preflight runs guards (skip_guard=False).

    Before this fix, batch preflight called prepare() with skip_guard=True,
    which meant guard-conditional templates crashed on rows where the guard
    would have skipped them. The fix passes skip_guard=False so the guard
    evaluates first, and skipped rows are advanced past without rendering.
    """

    def test_preflight_calls_prepare_with_skip_guard_false(self, batch_preparator):
        """Preflight must call TaskPreparer.prepare with skip_guard=False."""
        agent_config = {"name": "test_action", "prompt": "{{ content }}"}
        data = [{"target_id": "1", "content": {"field": "value"}}]

        mock_passed = MagicMock()
        mock_passed.guard_status = GuardStatus.PASSED

        with patch("agent_actions.llm.batch.processing.preparator.get_task_preparer") as mock_get:
            mock_preparer = MagicMock()
            mock_preparer.prepare.return_value = mock_passed
            mock_get.return_value = mock_preparer

            batch_preparator._run_preflight_validation(agent_config, data)

            call_kwargs = mock_preparer.prepare.call_args
            assert call_kwargs.kwargs.get("skip_guard") is False, (
                "Preflight must pass skip_guard=False so guards are evaluated. "
                "skip_guard=True would hide template errors behind guard-skipped rows."
            )

    def test_preflight_advances_past_guard_skipped_rows(self, batch_preparator):
        """When all sample rows are guard-skipped, preflight completes without error."""
        agent_config = {
            "name": "test_action",
            "prompt": "{{ upstream_ns.field }}",
            "guard": {"clause": "upstream_ns.has_data == true", "behavior": "skip"},
        }
        data = [
            {"target_id": "1", "content": {}},
            {"target_id": "2", "content": {}},
        ]

        mock_skipped = MagicMock()
        mock_skipped.guard_status = GuardStatus.SKIPPED

        with patch("agent_actions.llm.batch.processing.preparator.get_task_preparer") as mock_get:
            mock_preparer = MagicMock()
            mock_preparer.prepare.return_value = mock_skipped
            mock_get.return_value = mock_preparer

            # Must not raise TemplateVariableError
            batch_preparator._run_preflight_validation(agent_config, data)

            # All rows were attempted (not short-circuited on first skip)
            assert mock_preparer.prepare.call_count == len(data)

    def test_preflight_advances_past_upstream_unprocessed_rows(self, batch_preparator):
        """UPSTREAM_UNPROCESSED rows are skipped during preflight — no template rendered."""
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

            batch_preparator._run_preflight_validation(agent_config, data)
            assert mock_preparer.prepare.call_count == 2


class TestU02OnlineSkipGuardFalse:
    """Online process_record default skip_guard=False.

    The online per-record path (OnlineLLMStrategy.process_record) must default
    to skip_guard=False so that guards evaluate for each record. If the default
    were True, guards would silently pass in online mode while failing in batch.
    """

    def test_process_record_skip_guard_default_is_false(self):
        """process_record signature must default skip_guard to False."""
        from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy

        sig = inspect.signature(OnlineLLMStrategy.process_record)
        skip_guard_param = sig.parameters["skip_guard"]
        assert skip_guard_param.default is False, (
            "skip_guard default must be False so per-record guard evaluates. "
            "True would silently bypass guards in online mode."
        )

    def test_process_record_evaluates_guard_when_configured(self):
        """When guard is configured and skip_guard=False, guard must be evaluated."""
        from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy

        strategy = OnlineLLMStrategy.__new__(OnlineLLMStrategy)
        strategy._invocation_strategy = MagicMock()

        mock_prepared = MagicMock()
        mock_prepared.guard_status = GuardStatus.SKIPPED
        mock_prepared.source_guid = "sg_1"
        mock_prepared.source_snapshot = {"field": "val"}
        mock_prepared.original_content = {"field": "val"}

        context = MagicMock()
        context.agent_name = "test_action"
        context.action_name = "test_action"
        context.record_index = 0

        item = {"content": {"field": "val"}}

        with (
            patch("agent_actions.processing.strategies.online_llm.get_task_preparer") as mock_get,
            patch("agent_actions.processing.strategies.online_llm.build_tombstone") as mock_tomb,
            patch("agent_actions.processing.strategies.online_llm.fire_event"),
        ):
            mock_preparer = MagicMock()
            mock_preparer.prepare.return_value = mock_prepared
            mock_get.return_value = mock_preparer

            mock_tomb.return_value = {"content": {}, "_state": "guard_skipped"}

            result = strategy.process_record(item, context)

            # Verify prepare was called (guard evaluated)
            mock_preparer.prepare.assert_called_once()
            # SKIPPED path must build a tombstone and mark result as not executed
            mock_tomb.assert_called_once()
            assert result.executed is False


class TestU04SharedBuildPipelineContext:
    """Both batch and online paths call _build_pipeline_context.

    _build_pipeline_context is a static method that builds shared context
    (agent_indices, dependency_configs, version_context) BEFORE the batch/online
    fork. Both paths must use this single builder to prevent context divergence.
    """

    def test_build_pipeline_context_exists_as_static_method(self):
        """_build_pipeline_context must exist as a static method on ProcessingPipeline."""
        from agent_actions.workflow.pipeline import ProcessingPipeline

        assert hasattr(ProcessingPipeline, "_build_pipeline_context")
        assert isinstance(
            inspect.getattr_static(ProcessingPipeline, "_build_pipeline_context"),
            staticmethod,
        )

    def test_build_pipeline_context_returns_three_tuple(self):
        """Must return (agent_indices, dependency_configs, version_context)."""
        from agent_actions.workflow.pipeline import ProcessingPipeline

        result = ProcessingPipeline._build_pipeline_context(
            action_config={},
            action_configs={"step_a": {"idx": 0}, "step_b": {"idx": 1}},
        )
        assert len(result) == 3
        agent_indices, dependency_configs, version_context = result
        assert agent_indices == {"step_a": 0, "step_b": 1}
        assert dependency_configs is not None
        assert version_context is None  # non-versioned agent

    def test_build_pipeline_context_output_compatible_with_batch_preparator(self):
        """_build_pipeline_context output is accepted by BatchTaskPreparator constructor."""
        from agent_actions.workflow.pipeline import ProcessingPipeline

        # Verify the static method produces correct indices
        action_configs = {"extract": {"idx": 0}, "transform": {"idx": 1}}
        agent_indices, dep_configs, _ = ProcessingPipeline._build_pipeline_context(
            action_config={}, action_configs=action_configs
        )

        # BatchTaskPreparator accepts these as constructor args
        preparator = BatchTaskPreparator(
            action_indices=agent_indices,
            dependency_configs=dep_configs,
        )
        assert preparator is not None

    def test_online_path_receives_same_context_fields(self):
        """Online ProcessingContext uses same fields as batch PreparationContext.

        Both contexts must carry agent_indices, dependency_configs, version_context.
        These are populated from _build_pipeline_context output.
        """
        from agent_actions.processing.types import ProcessingContext

        sig = inspect.signature(ProcessingContext)
        params = sig.parameters

        # ProcessingContext must accept the same fields that _build_pipeline_context returns
        assert "agent_indices" in params, (
            "ProcessingContext must accept agent_indices from _build_pipeline_context"
        )
        assert "dependency_configs" in params, (
            "ProcessingContext must accept dependency_configs from _build_pipeline_context"
        )
        assert "version_context" in params, (
            "ProcessingContext must accept version_context from _build_pipeline_context"
        )

    def test_version_context_copied_to_prevent_mutation(self):
        """_build_pipeline_context must copy version_context to prevent cross-path mutation."""
        from agent_actions.workflow.pipeline import ProcessingPipeline

        original = {"i": 0, "length": 3}
        action_config = {
            "is_versioned_agent": True,
            "_version_context": original,
        }

        _, _, version_context = ProcessingPipeline._build_pipeline_context(
            action_config=action_config,
            action_configs=None,
        )

        assert version_context == original
        assert version_context is not original, (
            "version_context must be a copy — mutation in one path must not affect the other"
        )


class TestPairedExecutionFixture:
    """Verify the paired_execution fixture works for subsequent phases."""

    def test_paired_execution_both_pass_without_guard(self, paired_execution, sample_records):
        """Without guard config, both paths should pass all records."""
        online, batch = paired_execution(sample_records)
        assert online == ["passed"] * len(sample_records)
        assert batch == ["passed"] * len(sample_records)

    def test_paired_execution_same_decisions_with_guard(self, paired_execution):
        """With a guard, both paths must make identical pass/skip decisions."""
        records = [
            {"target_id": "t-001", "content": {"upstream_ns": {"status": "ready"}}},
            {"target_id": "t-002", "content": {"upstream_ns": {"status": "pending"}}},
            {"target_id": "t-003", "content": {"upstream_ns": {"status": "ready"}}},
        ]
        guard_config = {
            "clause": "upstream_ns.status == 'ready'",
            "behavior": "skip",
        }

        online, batch = paired_execution(records, guard_config)

        assert online == batch, f"Guard parity violation: online={online}, batch={batch}"
        assert online == ["passed", "skipped", "passed"]

    def test_paired_execution_returns_correct_types(self, paired_execution):
        """Return values are lists of strings (not mock objects)."""
        records = [{"target_id": "t-001", "content": {"upstream_ns": {"status": "ready"}}}]
        guard_config = {"clause": "upstream_ns.status == 'ready'", "behavior": "skip"}

        online, batch = paired_execution(records, guard_config)

        assert isinstance(online, list)
        assert isinstance(batch, list)
        assert all(isinstance(d, str) for d in online)
        assert all(isinstance(d, str) for d in batch)
