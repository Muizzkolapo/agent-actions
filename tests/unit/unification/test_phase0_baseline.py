"""Phase 0 baseline tests — verify unification prerequisites are in place.

These tests prove that Phase 0 items U-0.1 through U-0.4 are implemented
on the current codebase. If any Phase 0 item were reverted, the corresponding
test would fail.

Each test exercises real code paths (not mocks of the unit under test) to
verify the behavior that subsequent phases depend on.
"""

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.processing.prepared_task import GuardStatus


class TestU01BatchPreflightGuardAware:
    """U-0.1: Batch preflight runs guards (skip_guard=False).

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

            # Must not raise — before U-0.1, this crashed with TemplateVariableError
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
    """U-0.2: Online process_record default skip_guard=False.

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


class TestU03PrefilterUsesEvalItem:
    """U-0.3: Prefilter passes context=eval_item to evaluator.

    The guard evaluator must receive the record's existing content as its
    context parameter, not an empty dict or None. This ensures guard clauses
    that reference upstream namespace fields (e.g., upstream_ns.status) can
    resolve correctly in the online prefilter path.
    """

    def test_prefilter_passes_content_as_context(self):
        """prefilter_by_guard must pass record content as context to evaluator."""
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
                result = MagicMock()
                result.should_execute = True
                return result

            mock_evaluator.evaluate.side_effect = capture_evaluate
            mock_get_eval.return_value = mock_evaluator

            prefilter_by_guard(data, agent_config, "test_action")

            # Context must be the record's existing content — not empty or None
            assert captured_contexts[0] == {"upstream_ns": {"status": "ready"}}, (
                "First record's context must be its content dict"
            )
            assert captured_contexts[1] == {"upstream_ns": {"status": "pending"}}, (
                "Second record's context must be its content dict"
            )

    def test_prefilter_context_equals_eval_item(self):
        """context parameter must be identical to item parameter (both are eval_item)."""
        from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

        guard_config = {"clause": "field == 'x'", "behavior": "filter"}
        agent_config = {"guard": guard_config}
        data = [{"content": {"field": "x"}}]

        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator"
        ) as mock_get_eval:
            mock_evaluator = MagicMock()
            captured_args: list[dict] = []

            def capture_evaluate(*, item, guard_config, context=None, **kwargs):
                captured_args.append({"item": item, "context": context})
                result = MagicMock()
                result.should_execute = True
                return result

            mock_evaluator.evaluate.side_effect = capture_evaluate
            mock_get_eval.return_value = mock_evaluator

            prefilter_by_guard(data, agent_config, "test_action")

            # item and context must be the same object (both = eval_item)
            assert captured_args[0]["item"] is captured_args[0]["context"], (
                "item and context must be the same eval_item object"
            )


class TestU04SharedBuildPipelineContext:
    """U-0.4: Both batch and online paths call _build_pipeline_context.

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
