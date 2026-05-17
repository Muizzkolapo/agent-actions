"""Phase 9c: Filter/Skip/Observe consistency tests — U-4.3.

Tests that filtered and skipped namespaces produce identical observe
behavior: both resolve to None instead of crashing.  Covers the TDD
contract class TestFilteredNamespaceObserve plus filter/skip symmetry
and fan-in interaction scenarios.

Design gap 6: filter deletes ns; skip writes null — observe must treat
both as "null namespace → field resolves to None".  The implementation
represents both as None in field_context (no NullNamespace sentinel),
so the symmetry is structural.
"""

import pytest

from agent_actions.errors import RecordContextError
from agent_actions.prompt.context.scope_application import apply_context_scope


def _make_field_context(**namespaces):
    """Build a field_context dict from namespace kwargs."""
    return dict(namespaces)


# ── TDD Contract: TestFilteredNamespaceObserve (U-4.3) ─────────────


class TestFilteredNamespaceObserve:
    """U-4.3: Filtered namespace must be observable as null."""

    def test_observe_from_filtered_namespace(self):
        """Observing a field from a filtered upstream → None, not crash.

        Adapted from TDD contract: uses None (the actual representation
        of a filtered namespace in field_context) instead of the
        aspirational NullNamespace(reason='filtered') sentinel.
        """
        fc = _make_field_context(filtered_step=None)
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["filtered_step.field"]},
            action_name="downstream",
        )
        assert llm_ctx["filtered_step"]["field"] is None

    def test_fan_in_with_filtered_upstream(self):
        """Fan-in delivers record where one upstream was filtered; observe doesn't crash."""
        fc = _make_field_context(
            path_a={"result": "success"},
            path_b=None,  # filtered by guard
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["path_a.result", "path_b.field"]},
            action_name="fan_in_consumer",
        )
        assert llm_ctx["path_a"]["result"] == "success"
        assert llm_ctx["path_b"]["field"] is None

    def test_multiple_fields_from_filtered_namespace_all_none(self):
        """All fields from a filtered namespace resolve to None."""
        fc = _make_field_context(filtered=None)
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["filtered.a", "filtered.b", "filtered.c"]},
            action_name="downstream",
        )
        assert llm_ctx["filtered"] == {"a": None, "b": None, "c": None}

    def test_wildcard_on_filtered_namespace_is_empty(self):
        """Wildcard observe on filtered namespace extracts nothing (no fields to expand)."""
        fc = _make_field_context(filtered=None)
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["filtered.*"]},
            action_name="downstream",
        )
        assert "filtered" not in llm_ctx


# ── Filter/Skip symmetry ───────────────────────────────────────────


class TestFilterSkipObserveSymmetry:
    """Filter and skip must produce identical observe behavior."""

    def test_all_directives_null_safe_on_filtered(self):
        """Observe, passthrough, and drop all handle a filtered namespace without crash."""
        fc = _make_field_context(filtered=None, present={"val": 42})
        _, llm_ctx, pt = apply_context_scope(
            field_context=fc,
            context_scope={
                "observe": ["filtered.status", "present.val"],
                "passthrough": ["filtered.trace_id"],
                "drop": ["filtered.secret"],
            },
            action_name="downstream",
        )
        assert llm_ctx["filtered"]["status"] is None
        assert llm_ctx["present"]["val"] == 42
        assert pt["filtered"]["trace_id"] is None

    def test_passthrough_from_filtered_matches_skipped(self):
        """Passthrough from filtered namespace yields None, same as skipped."""
        fc = _make_field_context(upstream=None)
        _, _, pt = apply_context_scope(
            field_context=fc,
            context_scope={"passthrough": ["upstream.trace_id"]},
            action_name="downstream",
        )
        assert pt["upstream"]["trace_id"] is None

    def test_drop_on_filtered_namespace_no_crash(self):
        """Drop directive on filtered (None) namespace is a no-op, no crash."""
        fc = _make_field_context(filtered=None, present={"keep": "yes"})
        prompt_ctx, _, _ = apply_context_scope(
            field_context=fc,
            context_scope={"drop": ["filtered.secret"], "observe": ["present.keep"]},
            action_name="downstream",
        )
        assert "filtered" not in prompt_ctx
        assert prompt_ctx["present"]["keep"] == "yes"

    def test_absent_namespace_still_errors(self):
        """Namespace not in field_context at all → error (config bug / typo).

        This distinguishes "filtered/skipped" (None in field_context) from
        "never declared" (absent from field_context entirely).
        """
        fc = _make_field_context(present={"f": 1})
        with pytest.raises(RecordContextError, match="not found at runtime"):
            apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["ghost.field"]},
                action_name="downstream",
            )


# ── Fan-in interaction matrix ──────────────────────────────────────


class TestFanInFilterInteractions:
    """Fan-in scenarios with mixed null/present/absent namespaces."""

    def test_three_way_fan_in_one_filtered(self):
        """Three upstream paths, one filtered: observe resolves all correctly."""
        fc = _make_field_context(
            step_a={"score": 95},
            step_b=None,  # filtered
            step_c={"label": "good"},
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={
                "observe": ["step_a.score", "step_b.rating", "step_c.label"],
            },
            action_name="aggregator",
        )
        assert llm_ctx["step_a"]["score"] == 95
        assert llm_ctx["step_b"]["rating"] is None
        assert llm_ctx["step_c"]["label"] == "good"

    def test_fan_in_observe_and_passthrough_on_filtered(self):
        """Both observe and passthrough on a filtered namespace in fan-in."""
        fc = _make_field_context(
            success_path={"output": "data"},
            filtered_path=None,
        )
        _, llm_ctx, pt = apply_context_scope(
            field_context=fc,
            context_scope={
                "observe": ["success_path.output", "filtered_path.result"],
                "passthrough": ["filtered_path.id"],
            },
            action_name="merger",
        )
        assert llm_ctx["success_path"]["output"] == "data"
        assert llm_ctx["filtered_path"]["result"] is None
        assert pt["filtered_path"]["id"] is None

    def test_all_upstream_filtered_still_works(self):
        """All upstream namespaces filtered: all fields resolve to None."""
        fc = _make_field_context(dep_a=None, dep_b=None)
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["dep_a.x", "dep_b.y"]},
            action_name="downstream",
        )
        assert llm_ctx["dep_a"]["x"] is None
        assert llm_ctx["dep_b"]["y"] is None
