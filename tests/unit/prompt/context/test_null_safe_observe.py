"""Tests for null-safe observe/passthrough resolution (specs 401 + 402).

When a guard skips or filters an upstream action, its namespace is null
on the record.  Downstream observe/passthrough must yield None for its
fields instead of raising ConfigurationError.
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_application import apply_context_scope


def _make_field_context(**namespaces):
    """Build a field_context dict from namespace kwargs.

    Example: _make_field_context(dep={"f": 1}, skipped=None)
    """
    return dict(namespaces)


# ── Observe: null namespace (guard-skipped) ──────────────────────────


class TestObserveNullNamespace:
    """Spec 401: observe from guard-skipped namespace yields None."""

    def test_specific_field_yields_none(self):
        """observe: ['skipped.field'] where skipped is None → field is None, no crash."""
        fc = _make_field_context(skipped=None)
        prompt_ctx, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped.field"]},
            action_name="downstream",
        )
        assert llm_ctx["skipped"]["field"] is None

    def test_multiple_fields_all_yield_none(self):
        """Multiple fields from a null namespace all resolve to None."""
        fc = _make_field_context(skipped=None)
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped.a", "skipped.b", "skipped.c"]},
            action_name="downstream",
        )
        assert llm_ctx["skipped"] == {"a": None, "b": None, "c": None}

    def test_wildcard_on_null_namespace_is_empty(self):
        """observe: ['skipped.*'] where skipped is None → no fields extracted (already safe)."""
        fc = _make_field_context(skipped=None)
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped.*"]},
            action_name="downstream",
        )
        assert "skipped" not in llm_ctx

    def test_mixed_null_and_present_namespaces(self):
        """Normal namespace works; null namespace yields None."""
        fc = _make_field_context(
            present={"score": 95},
            skipped=None,
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["present.score", "skipped.status"]},
            action_name="downstream",
        )
        assert llm_ctx["present"]["score"] == 95
        assert llm_ctx["skipped"]["status"] is None

    def test_null_namespace_in_prompt_context(self):
        """Null namespace appears in prompt_context as None (for template rendering)."""
        fc = _make_field_context(skipped=None)
        prompt_ctx, _, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped.field"]},
            action_name="downstream",
        )
        assert prompt_ctx["skipped"] is None


# ── Observe: strict mode preserved ───────────────────────────────────


class TestObserveStrictPreserved:
    """Normal observe behavior is unchanged: missing field from present namespace still crashes."""

    def test_missing_field_from_present_namespace_raises(self):
        """observe: ['dep.nonexistent'] where dep is a real dict → ConfigurationError."""
        fc = _make_field_context(dep={"actual_field": "value"})
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["dep.nonexistent"]},
                action_name="downstream",
            )

    def test_undeclared_namespace_raises(self):
        """observe: ['ghost.field'] where ghost is not in field_context → ConfigurationError."""
        fc = _make_field_context(dep={"f": 1})
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=fc,
                context_scope={"observe": ["ghost.field"]},
                action_name="downstream",
            )


# ── Passthrough: null namespace ──────────────────────────────────────


class TestPassthroughNullNamespace:
    """Spec 401/402: passthrough from guard-skipped namespace yields None."""

    def test_specific_field_yields_none(self):
        """passthrough: ['skipped.field'] where skipped is None → field is None."""
        fc = _make_field_context(skipped=None)
        _, _, pt = apply_context_scope(
            field_context=fc,
            context_scope={"passthrough": ["skipped.field"]},
            action_name="downstream",
        )
        assert pt["skipped"]["field"] is None

    def test_wildcard_on_null_namespace_is_empty(self):
        """passthrough: ['skipped.*'] where skipped is None → no fields extracted."""
        fc = _make_field_context(skipped=None)
        _, _, pt = apply_context_scope(
            field_context=fc,
            context_scope={"passthrough": ["skipped.*"]},
            action_name="downstream",
        )
        assert "skipped" not in pt

    def test_passthrough_strict_preserved(self):
        """passthrough: ['dep.nonexistent'] from present namespace → ConfigurationError."""
        fc = _make_field_context(dep={"actual": "value"})
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(
                field_context=fc,
                context_scope={"passthrough": ["dep.nonexistent"]},
                action_name="downstream",
            )


# ── Drop: null namespace ─────────────────────────────────────────────


class TestDropNullNamespace:
    """Drop on null namespace should not crash (already safe via isinstance check)."""

    def test_drop_on_null_namespace_no_crash(self):
        """drop: ['skipped.field'] where skipped is None → no crash, valid return."""
        fc = _make_field_context(skipped=None)
        prompt_ctx, llm_ctx, pt = apply_context_scope(
            field_context=fc,
            context_scope={"drop": ["skipped.field"]},
            action_name="downstream",
        )
        assert isinstance(prompt_ctx, dict)
        assert isinstance(llm_ctx, dict)
        assert isinstance(pt, dict)


# ── Gating: null namespace ───────────────────────────────────────────


class TestGatingNullNamespace:
    """The gating phase (prompt_context filtering) handles None correctly."""

    def test_null_namespace_passes_through_gate(self):
        """Null namespace in allowed set passes gating as None."""
        fc = _make_field_context(skipped=None, present={"f": 1})
        prompt_ctx, _, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["skipped.status", "present.f"]},
            action_name="downstream",
        )
        assert prompt_ctx["skipped"] is None
        assert prompt_ctx["present"]["f"] == 1


# ── Fan-in: filter scenario (spec 402) ──────────────────────────────


class TestFanInFilterScenario:
    """Spec 402: fan-in where one branch was guard-filtered."""

    def test_observe_from_filtered_branch(self):
        """Action D depends on B and C; C was guard-filtered.

        D's merged record has B's namespace but C is None.
        Observe from C.field should yield None.
        """
        fc = _make_field_context(
            action_b={"output": "processed"},
            action_c=None,  # guard-filtered: arrived via different branch
        )
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={"observe": ["action_b.output", "action_c.reason"]},
            action_name="downstream",
        )
        assert llm_ctx["action_b"]["output"] == "processed"
        assert llm_ctx["action_c"]["reason"] is None

    def test_passthrough_from_filtered_branch(self):
        """Passthrough from filtered branch yields None."""
        fc = _make_field_context(
            action_b={"id": "abc"},
            action_c=None,
        )
        _, _, pt = apply_context_scope(
            field_context=fc,
            context_scope={"passthrough": ["action_b.id", "action_c.trace_id"]},
            action_name="downstream",
        )
        assert pt["action_b"]["id"] == "abc"
        assert pt["action_c"]["trace_id"] is None


# ── Combined: observe + passthrough + drop on null ───────────────────


class TestCombinedDirectivesNullNamespace:
    """Interaction of multiple directives when one namespace is null."""

    def test_observe_and_passthrough_both_null_safe(self):
        """Both observe and passthrough on the same null namespace yield None."""
        fc = _make_field_context(skipped=None)
        _, llm_ctx, pt = apply_context_scope(
            field_context=fc,
            context_scope={
                "observe": ["skipped.status"],
                "passthrough": ["skipped.trace_id"],
            },
            action_name="downstream",
        )
        assert llm_ctx["skipped"]["status"] is None
        assert pt["skipped"]["trace_id"] is None

    def test_drop_then_observe_on_null_no_crash(self):
        """Drop + observe on null namespace: drop is no-op, observe yields None."""
        fc = _make_field_context(skipped=None)
        _, llm_ctx, _ = apply_context_scope(
            field_context=fc,
            context_scope={
                "drop": ["skipped.secret"],
                "observe": ["skipped.status"],
            },
            action_name="downstream",
        )
        assert llm_ctx["skipped"]["status"] is None
