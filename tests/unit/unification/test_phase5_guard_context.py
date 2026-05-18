"""Phase 5: Guard context alignment tests.

Verifies that online prefilter and batch prepare produce identical guard
decisions for the same record when the guard references fields only
available through full context building (source namespace, version
namespace, output_field promotion).

Commit A: These tests FAIL (prefilter doesn't build full context).
Commit C: Tests turn green (prefilter wired to build_guard_context).
"""

from __future__ import annotations

from typing import Any

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.processing.guard_context import build_guard_context
from agent_actions.utils.content import get_existing_content
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evaluate_guard_with_full_context(
    record: dict[str, Any],
    guard_config: dict[str, Any],
    *,
    agent_name: str = "test_action",
    agent_config: dict[str, Any] | None = None,
    agent_indices: dict[str, int] | None = None,
    source_content: Any = None,
    source_data: list[dict[str, Any]] | None = None,
    version_context: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    dependency_configs: dict[str, Any] | None = None,
) -> bool:
    """Evaluate guard using the shared build_guard_context (batch-equivalent path)."""
    evaluator = GuardEvaluator()
    content = get_existing_content(record)
    config = agent_config or {"name": agent_name}

    field_context = build_guard_context(
        record,
        agent_name=agent_name,
        agent_config=config,
        agent_indices=agent_indices,
        source_content=source_content,
        source_data=source_data,
        version_context=version_context,
        workflow_metadata=workflow_metadata,
        dependency_configs=dependency_configs,
    )

    result = evaluator.evaluate(item=content, guard_config=guard_config, context=field_context)
    return result.should_execute


# ---------------------------------------------------------------------------
# Tests — Guard Context Parity via prefilter_by_guard
# ---------------------------------------------------------------------------


class TestGuardContextParity:
    """U-1.1: Prefilter and prepare must use same guard context."""

    def test_source_namespace_parity(self):
        """Guard referencing source.name passes when source_data provides it.

        prefilter_by_guard with source_data builds full context including
        source namespace, so the guard finds source.name and passes.
        """
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"text": "hello"},
            }
        ]
        source_data = [{"source_guid": "sg-001", "name": "test_source", "id": "src-1"}]
        guard_config = {
            "clause": "source.name == 'test_source'",
            "behavior": "skip",
        }
        agent_config = {"name": "test_action", "guard": guard_config}

        passing, skipped, _ = prefilter_by_guard(
            records,
            agent_config,
            "test_action",
            source_data=source_data,
        )

        assert len(passing) == 1, (
            f"Guard should pass (source.name == 'test_source') but got "
            f"{len(passing)} passing, {len(skipped)} skipped. "
            "Prefilter context is missing source namespace."
        )

    def test_version_namespace_parity(self):
        """Guard referencing version.i passes when version_context is provided."""
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"text": "hello"},
            }
        ]
        guard_config = {
            "clause": "version.i > 0",
            "behavior": "skip",
        }
        agent_config = {"name": "test_action", "guard": guard_config}

        passing, skipped, _ = prefilter_by_guard(
            records,
            agent_config,
            "test_action",
            version_context={"i": 1, "idx": 1, "length": 3},
        )

        assert len(passing) == 1, (
            f"Guard should pass (version.i=1 > 0) but got "
            f"{len(passing)} passing, {len(skipped)} skipped. "
            "Prefilter context is missing version namespace."
        )

    def test_output_field_promotion_parity(self):
        """Guard referencing promoted output_field passes with dependency_configs.

        When upstream action 'assess' has output_field='severity', batch
        promotes field_context['severity'] = 'high'. With proper config,
        prefilter does the same via build_guard_context.
        """
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"assess": {"severity": "high", "details": "..."}},
            }
        ]
        guard_config = {
            "clause": "severity == 'high'",
            "behavior": "skip",
        }
        agent_config = {
            "name": "test_action",
            "guard": guard_config,
            "prompt": "Handle: {{ assess.severity }}",
            "context_scope": {"observe": ["assess.*"]},
        }
        dependency_configs = {"assess": {"output_field": "severity"}}

        passing, skipped, _ = prefilter_by_guard(
            records,
            agent_config,
            "test_action",
            agent_indices={"assess": 0, "test_action": 1},
            dependency_configs=dependency_configs,
        )

        assert len(passing) == 1, (
            f"Guard should pass (promoted severity == 'high') but got "
            f"{len(passing)} passing, {len(skipped)} skipped. "
            "Prefilter context is missing promoted output_field."
        )

    def test_prefilter_matches_batch_context(self):
        """prefilter_by_guard with full context produces same decision as batch path."""
        record = {
            "target_id": "t-001",
            "source_guid": "sg-001",
            "content": {"text": "hello"},
        }
        source_data = [{"source_guid": "sg-001", "name": "test_source"}]
        guard_config = {
            "clause": "source.name == 'test_source'",
            "behavior": "skip",
        }
        agent_config = {"name": "test_action", "guard": guard_config}

        # Online path: prefilter_by_guard with pipeline context
        passing, _skipped, _ = prefilter_by_guard(
            [record],
            agent_config,
            "test_action",
            source_data=source_data,
        )
        online_passes = len(passing) == 1

        # Batch path: build_guard_context directly
        batch_passes = _evaluate_guard_with_full_context(
            record, guard_config, source_data=source_data
        )

        assert online_passes == batch_passes, (
            f"Guard parity violation: online={online_passes}, batch={batch_passes}"
        )


class TestCodeCenteredQuizGuard:
    """Acceptance criteria: code_centered_quiz guard with has_failures."""

    def test_has_failures_true_passes_guard(self):
        """has_failures=true → guard passes (action should run).

        When has_failures is a promoted output_field from upstream code_quiz,
        prefilter must promote it the same way batch does.
        """
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"code_quiz": {"has_failures": True, "score": 0.3}},
            }
        ]
        guard_config = {
            "clause": "has_failures",
            "behavior": "skip",
        }
        agent_config = {
            "name": "test_action",
            "guard": guard_config,
            "prompt": "Fix: {{ code_quiz.has_failures }}",
            "context_scope": {"observe": ["code_quiz.*"]},
        }
        dependency_configs = {"code_quiz": {"output_field": "has_failures"}}

        passing, skipped, _ = prefilter_by_guard(
            records,
            agent_config,
            "test_action",
            agent_indices={"code_quiz": 0, "test_action": 1},
            dependency_configs=dependency_configs,
        )

        assert len(passing) == 1, (
            f"Guard should pass (has_failures=True → truthy) but got "
            f"{len(passing)} passing, {len(skipped)} skipped. "
            "Prefilter doesn't promote output_field 'has_failures'."
        )

    def test_has_failures_false_skips_downstream(self):
        """has_failures=false → guard skips (downstream action should not run).

        Both paths agree: has_failures=False is falsy → not matched → skip.
        """
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"code_quiz": {"has_failures": False, "score": 1.0}},
            }
        ]
        guard_config = {
            "clause": "has_failures",
            "behavior": "skip",
        }
        agent_config = {
            "name": "test_action",
            "guard": guard_config,
            "prompt": "Fix: {{ code_quiz.has_failures }}",
            "context_scope": {"observe": ["code_quiz.*"]},
        }
        dependency_configs = {"code_quiz": {"output_field": "has_failures"}}

        passing, skipped, _ = prefilter_by_guard(
            records,
            agent_config,
            "test_action",
            agent_indices={"code_quiz": 0, "test_action": 1},
            dependency_configs=dependency_configs,
        )

        # has_failures=False → falsy → guard skips
        assert len(passing) == 0, (
            f"Guard should skip (has_failures=False) but {len(passing)} passed"
        )
        assert len(skipped) == 1


class TestPrefilterByGuardContextAlignment:
    """Integration: prefilter_by_guard builds full context when pipeline params available."""

    def test_no_pipeline_context_uses_eval_item(self):
        """Without pipeline context, prefilter falls back to eval_item (backward compat)."""
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"upstream_ns": {"status": "ready"}},
            }
        ]
        guard_config = {
            "clause": "upstream_ns.status == 'ready'",
            "behavior": "skip",
        }
        agent_config = {"name": "test_action", "guard": guard_config}

        # No pipeline context → uses eval_item (record content has upstream_ns)
        passing, skipped, _ = prefilter_by_guard(records, agent_config, "test_action")

        assert len(passing) == 1, "Should pass — field is in record content"

    def test_pipeline_context_enables_source_guard(self):
        """With source_data, guard referencing source namespace passes."""
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"text": "hello"},
            }
        ]
        source_data = [{"source_guid": "sg-001", "name": "test_source"}]
        guard_config = {
            "clause": "source.name == 'test_source'",
            "behavior": "skip",
        }
        agent_config = {"name": "test_action", "guard": guard_config}

        passing, skipped, _ = prefilter_by_guard(
            records,
            agent_config,
            "test_action",
            source_data=source_data,
        )

        assert len(passing) == 1, (
            f"Expected 1 passing (source.name matches) but got "
            f"{len(passing)} passing, {len(skipped)} skipped"
        )

    def test_multiple_records_mixed_decisions(self):
        """Multiple records with different guard outcomes are correctly split."""
        records = [
            {
                "target_id": "t-001",
                "source_guid": "sg-001",
                "content": {"assess": {"severity": "high"}},
            },
            {
                "target_id": "t-002",
                "source_guid": "sg-002",
                "content": {"assess": {"severity": "low"}},
            },
        ]
        guard_config = {
            "clause": "severity == 'high'",
            "behavior": "skip",
        }
        agent_config = {
            "name": "test_action",
            "guard": guard_config,
            "prompt": "Handle: {{ assess.severity }}",
            "context_scope": {"observe": ["assess.*"]},
        }
        dependency_configs = {"assess": {"output_field": "severity"}}

        passing, skipped, _ = prefilter_by_guard(
            records,
            agent_config,
            "test_action",
            agent_indices={"assess": 0, "test_action": 1},
            dependency_configs=dependency_configs,
        )

        assert len(passing) == 1, f"Only high-severity should pass, got {len(passing)}"
        assert passing[0]["target_id"] == "t-001"
        assert len(skipped) == 1
        assert skipped[0]["target_id"] == "t-002"


class TestPrefilterFallbackWarning:
    """Phase 5 hardening: log a warning when the eval_item-only fallback path runs.

    The fallback exists for test convenience but breaks online/batch guard parity
    if a production caller ever omits pipeline context kwargs. The warning makes
    the regression visible in ops logs instead of silently diverging.
    """

    def test_fallback_path_emits_warning(self, caplog):
        """When no pipeline context kwargs are passed, a single warning fires.

        Asserts: warning fires once per call (not per record), names the agent,
        mentions the diverging behavior so operators can act on the signal.
        """
        records = [
            {"target_id": "t-001", "source_guid": "sg-001", "content": {"x": 1}},
            {"target_id": "t-002", "source_guid": "sg-002", "content": {"x": 2}},
            {"target_id": "t-003", "source_guid": "sg-003", "content": {"x": 3}},
        ]
        agent_config = {
            "name": "test_action",
            "guard": {"clause": "x == 1", "behavior": "skip"},
        }

        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="agent_actions.workflow.pipeline_file_mode"):
            prefilter_by_guard(records, agent_config, "test_action")

        fallback_warnings = [
            r
            for r in caplog.records
            if r.levelno == _logging.WARNING
            and "prefilter_by_guard" in r.message
            and "without pipeline context" in r.message
        ]
        assert len(fallback_warnings) == 1, (
            "Expected exactly one fallback warning per call (not per record); "
            f"got {len(fallback_warnings)} for 3 input records"
        )
        assert "test_action" in fallback_warnings[0].message

    def test_pipeline_context_path_silent(self, caplog):
        """When pipeline context is supplied, no fallback warning fires.

        Confirms the warning only triggers on the fallback path — production
        callers (UnifiedProcessor._guard_filter*) that pass full context kwargs
        don't generate noise.
        """
        records = [{"target_id": "t-001", "source_guid": "sg-001", "content": {"x": 1}}]
        agent_config = {
            "name": "test_action",
            "guard": {"clause": "x == 1", "behavior": "skip"},
        }

        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="agent_actions.workflow.pipeline_file_mode"):
            prefilter_by_guard(
                records,
                agent_config,
                "test_action",
                source_data=[{"source_guid": "sg-001"}],
            )

        fallback_warnings = [
            r
            for r in caplog.records
            if r.levelno == _logging.WARNING and "without pipeline context" in r.message
        ]
        assert fallback_warnings == [], (
            "Pipeline-context path must not emit fallback warning; "
            f"unexpected warnings: {[r.message for r in fallback_warnings]}"
        )

    def test_no_guard_configured_silent(self, caplog):
        """When no guard is configured, the function returns early — no warning.

        The fallback warning is about guard *evaluation* divergence; if there's
        no guard to evaluate, the warning is irrelevant and would be noise.
        """
        records = [{"target_id": "t-001", "source_guid": "sg-001", "content": {"x": 1}}]
        agent_config = {"name": "test_action"}  # no guard key

        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="agent_actions.workflow.pipeline_file_mode"):
            prefilter_by_guard(records, agent_config, "test_action")

        fallback_warnings = [r for r in caplog.records if "without pipeline context" in r.message]
        assert fallback_warnings == [], "No guard configured → no fallback warning"
