"""Phase 5: Guard context alignment — TDD red tests.

Proves that online prefilter and batch prepare produce different guard
decisions for the same record when the guard references fields only
available through full context building (source namespace, version
namespace, output_field promotion).

These tests MUST FAIL against current code.
After Commit C (wire prefilter), they turn green.
"""

from __future__ import annotations

from typing import Any

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.prompt.context.scope_builder import build_field_context_with_history
from agent_actions.utils.content import get_existing_content
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

# ---------------------------------------------------------------------------
# Helpers — simulate batch and online guard evaluation paths
# ---------------------------------------------------------------------------


def _evaluate_guard_online(
    record: dict[str, Any],
    guard_config: dict[str, Any],
) -> bool:
    """Simulate the online prefilter guard path (current behavior).

    Mirrors prefilter_by_guard: context = eval_item = get_existing_content(record).
    """
    evaluator = GuardEvaluator()
    eval_item = get_existing_content(record)
    result = evaluator.evaluate(item=eval_item, guard_config=guard_config, context=eval_item)
    return result.should_execute


def _evaluate_guard_batch(
    record: dict[str, Any],
    guard_config: dict[str, Any],
    *,
    agent_name: str = "test_action",
    agent_config: dict[str, Any] | None = None,
    agent_indices: dict[str, int] | None = None,
    source_content: Any = None,
    version_context: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    dependency_configs: dict[str, Any] | None = None,
) -> bool:
    """Simulate the batch prepare guard path.

    Mirrors TaskPreparer.prepare: builds full field_context via
    build_field_context_with_history, then evaluates guard with that context.
    """
    evaluator = GuardEvaluator()
    content = get_existing_content(record)
    config = agent_config or {"name": agent_name}

    if source_content is None:
        source_content = content

    field_context = build_field_context_with_history(
        agent_name=agent_name,
        agent_config=config,
        agent_indices=agent_indices,
        source_content=source_content,
        version_context=version_context,
        workflow_metadata=workflow_metadata,
        current_item=record,
        context_scope=config.get("context_scope"),
    )
    field_context.pop("_dependency_metadata", None)

    # Promote output_field values (mirrors TaskPreparer._load_full_context)
    if dependency_configs:
        for dep_name, dep_config in dependency_configs.items():
            if not dep_config or "output_field" not in dep_config:
                continue
            of_name = dep_config["output_field"]
            dep_data = field_context.get(dep_name)
            if isinstance(dep_data, list) and len(dep_data) == 1:
                dep_data = dep_data[0]
            if isinstance(dep_data, dict) and of_name in dep_data:
                if of_name not in field_context:
                    field_context[of_name] = dep_data[of_name]

    result = evaluator.evaluate(item=content, guard_config=guard_config, context=field_context)
    return result.should_execute


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGuardContextParity:
    """U-1.1: Prefilter and prepare must use same guard context."""

    def test_source_namespace_parity(self):
        """Guard referencing source.name must produce same decision in both paths.

        Currently FAILS: prefilter passes context=eval_item (no source namespace),
        so source.name is missing → guard treats as 'not matched' → skip.
        Batch builds full field_context with source namespace → guard passes.
        """
        record = {
            "target_id": "t-001",
            "source_guid": "sg-001",
            "content": {"text": "hello"},
        }
        source_content = {"name": "test_source", "id": "src-1"}
        guard_config = {
            "clause": "source.name == 'test_source'",
            "behavior": "skip",
        }

        online_passes = _evaluate_guard_online(record, guard_config)
        batch_passes = _evaluate_guard_batch(
            record,
            guard_config,
            source_content=source_content,
        )

        # Batch passes (source.name found and matches).
        # Online must also pass — currently it doesn't.
        assert batch_passes is True, "Batch should pass (baseline)"
        assert online_passes == batch_passes, (
            f"Guard parity violation: online={online_passes}, batch={batch_passes}. "
            "Prefilter context is missing source namespace."
        )

    def test_version_namespace_parity(self):
        """Guard referencing version.i must produce same decision in both paths.

        Currently FAILS: prefilter context has no version namespace.
        """
        record = {
            "target_id": "t-001",
            "source_guid": "sg-001",
            "content": {"text": "hello"},
        }
        # version.i > 0 means "not the first iteration"
        guard_config = {
            "clause": "version.i > 0",
            "behavior": "skip",
        }

        online_passes = _evaluate_guard_online(record, guard_config)
        batch_passes = _evaluate_guard_batch(
            record,
            guard_config,
            version_context={"i": 1, "idx": 1, "length": 3},
        )

        assert batch_passes is True, "Batch should pass (version.i=1 > 0)"
        assert online_passes == batch_passes, (
            f"Guard parity violation: online={online_passes}, batch={batch_passes}. "
            "Prefilter context is missing version namespace."
        )

    def test_output_field_promotion_parity(self):
        """Guard referencing promoted output_field must produce same decision.

        When upstream action 'assess' has output_field='severity', batch
        promotes field_context['severity'] = 'high'. Prefilter doesn't.
        """
        record = {
            "target_id": "t-001",
            "source_guid": "sg-001",
            "content": {"assess": {"severity": "high", "details": "..."}},
        }
        guard_config = {
            "clause": "severity == 'high'",
            "behavior": "skip",
        }
        dependency_configs = {
            "assess": {"output_field": "severity"},
        }

        online_passes = _evaluate_guard_online(record, guard_config)
        batch_passes = _evaluate_guard_batch(
            record,
            guard_config,
            agent_indices={"assess": 0, "test_action": 1},
            dependency_configs=dependency_configs,
        )

        assert batch_passes is True, "Batch should pass (promoted severity == 'high')"
        assert online_passes == batch_passes, (
            f"Guard parity violation: online={online_passes}, batch={batch_passes}. "
            "Prefilter context is missing promoted output_field."
        )


class TestCodeCenteredQuizGuard:
    """Acceptance criteria: code_centered_quiz guard with has_failures."""

    def test_has_failures_true_passes_guard(self):
        """has_failures=true → guard passes (action should run).

        Guard clause: 'has_failures' (truthy check). When has_failures is True
        the guard condition is matched → action executes.

        Currently FAILS for online path when has_failures is a promoted
        output_field (not directly in record content at top level).
        """
        record = {
            "target_id": "t-001",
            "source_guid": "sg-001",
            "content": {"code_quiz": {"has_failures": True, "score": 0.3}},
        }
        guard_config = {
            "clause": "has_failures",
            "behavior": "skip",
        }
        dependency_configs = {
            "code_quiz": {"output_field": "has_failures"},
        }

        online_passes = _evaluate_guard_online(record, guard_config)
        batch_passes = _evaluate_guard_batch(
            record,
            guard_config,
            agent_indices={"code_quiz": 0, "test_action": 1},
            dependency_configs=dependency_configs,
        )

        assert batch_passes is True, "Batch should pass (has_failures=True → truthy)"
        assert online_passes == batch_passes, (
            f"Guard parity violation: online={online_passes}, batch={batch_passes}. "
            "Prefilter doesn't promote output_field 'has_failures'."
        )

    def test_has_failures_false_skips_downstream(self):
        """has_failures=false → guard skips (downstream action should not run).

        Both paths should agree: has_failures=False is falsy → not matched → skip.
        """
        record = {
            "target_id": "t-001",
            "source_guid": "sg-001",
            "content": {"code_quiz": {"has_failures": False, "score": 1.0}},
        }
        guard_config = {
            "clause": "has_failures",
            "behavior": "skip",
        }
        dependency_configs = {
            "code_quiz": {"output_field": "has_failures"},
        }

        online_passes = _evaluate_guard_online(record, guard_config)
        batch_passes = _evaluate_guard_batch(
            record,
            guard_config,
            agent_indices={"code_quiz": 0, "test_action": 1},
            dependency_configs=dependency_configs,
        )

        # Both should skip (has_failures is falsy)
        assert batch_passes is False, "Batch should skip (has_failures=False)"
        assert online_passes == batch_passes, (
            f"Guard parity violation: online={online_passes}, batch={batch_passes}"
        )


class TestPrefilterByGuardContextAlignment:
    """Integration: prefilter_by_guard must build full context when pipeline context available."""

    def test_prefilter_passes_with_source_guard(self):
        """prefilter_by_guard with source-referencing guard should pass record.

        Currently FAILS: prefilter_by_guard doesn't accept or use pipeline
        context, so source namespace is never built.
        """
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"text": "hello"},
            }
        ]
        guard_config = {
            "clause": "source.name == 'test_source'",
            "behavior": "skip",
        }
        agent_config = {"name": "test_action", "guard": guard_config}

        # After fix: prefilter_by_guard will accept pipeline_context and build
        # full context including source namespace. For now, this call uses the
        # existing signature — the test fails because source.name is missing.
        passing, skipped, _ = prefilter_by_guard(records, agent_config, "test_action")

        assert len(passing) == 1, (
            f"Expected 1 passing record (source.name matches) but got "
            f"{len(passing)} passing, {len(skipped)} skipped. "
            "prefilter_by_guard needs full context to evaluate source-referencing guards."
        )
