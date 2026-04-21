"""Tests for tool UDF observe namespace normalization.

Verifies that tool UDF outputs are injected with the same namespace
structure as LLM outputs, so downstream observe references resolve
identically regardless of source action kind.
"""

import pytest

from agent_actions.prompt.context.scope_application import (
    apply_context_scope,
    flatten_observe_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_field_context(action_name: str, fields: dict) -> dict:
    """Build a minimal field_context with one namespace."""
    return {action_name: fields}


# ---------------------------------------------------------------------------
# 1. Tool UDF observe — flat injection
# ---------------------------------------------------------------------------


class TestToolUdfFlatInjection:
    """Downstream observe: [tool.field] resolves the same as for LLM actions."""

    def test_single_field_resolves(self):
        """observe: ['tool.answer'] finds 'answer' when tool output is flat."""
        field_context = _build_field_context("tool", {"answer": "42"})
        _, llm_ctx, _ = apply_context_scope(
            field_context,
            {"observe": ["tool.answer"]},
            action_name="downstream",
        )
        assert llm_ctx == {"tool": {"answer": "42"}}

    def test_flatten_removes_namespace_wrapper(self):
        namespaced = {"upstream": {"question_type": "yes_no"}}
        flat = flatten_observe_context(namespaced)
        assert flat == {"question_type": "yes_no"}
        assert "upstream" not in flat

    def test_flatten_empty(self):
        assert flatten_observe_context({}) == {}

    def test_flatten_non_dict_value_preserved(self):
        ctx = {"scalar_ns": "just_a_string"}
        flat = flatten_observe_context(ctx)
        assert flat == {"scalar_ns": "just_a_string"}


# ---------------------------------------------------------------------------
# 2. Tool UDF observe — multiple fields
# ---------------------------------------------------------------------------


class TestToolUdfMultipleFields:
    """All fields accessible without extra nesting."""

    def test_multiple_fields_from_single_namespace(self):
        namespaced = {"A": {"question_type": "yes_no", "confidence": 0.95}}
        flat = flatten_observe_context(namespaced)
        assert flat["question_type"] == "yes_no"
        assert flat["confidence"] == 0.95

    def test_fields_from_multiple_namespaces_no_collision(self):
        namespaced = {
            "A": {"question_type": "yes_no"},
            "source": {"url": "http://example.com"},
        }
        flat = flatten_observe_context(namespaced)
        assert flat["question_type"] == "yes_no"
        assert flat["url"] == "http://example.com"

    def test_collision_qualified_keys(self):
        namespaced = {
            "dep_a": {"title": "Title A", "unique_a": "val_a"},
            "dep_b": {"title": "Title B"},
        }
        flat = flatten_observe_context(namespaced)
        assert flat["dep_a.title"] == "Title A"
        assert flat["dep_b.title"] == "Title B"
        assert flat["unique_a"] == "val_a"
        # Bare 'title' should NOT exist (it's ambiguous)
        assert "title" not in flat


# ---------------------------------------------------------------------------
# 3. LLM observe — unchanged
# ---------------------------------------------------------------------------


class TestLlmObserveUnchanged:
    """Existing LLM observe behavior is not affected by the fix."""

    def test_llm_context_stays_namespaced(self):
        """apply_context_scope still returns namespaced llm_context."""
        field_context = {
            "classify": {"question_type": "yes_no", "confidence": 0.95},
        }
        _, llm_ctx, _ = apply_context_scope(
            field_context,
            {"observe": ["classify.question_type"]},
            action_name="downstream",
        )
        assert llm_ctx == {"classify": {"question_type": "yes_no"}}

    def test_wildcard_observe_namespaced(self):
        field_context = {"dep": {"a": 1, "b": 2}}
        _, llm_ctx, _ = apply_context_scope(
            field_context,
            {"observe": ["dep.*"]},
            action_name="downstream",
        )
        assert llm_ctx == {"dep": {"a": 1, "b": 2}}


# ---------------------------------------------------------------------------
# 4. Cross-action observe — tool feeds LLM
# ---------------------------------------------------------------------------


class TestCrossActionToolFeedsLlm:
    """Tool UDF output consumed by LLM action via observe resolves correctly."""

    def test_tool_output_flat_resolves_in_downstream(self):
        """After flatten, tool passes flat fields → downstream observe works."""
        # Simulate: tool received namespaced context, we flattened it
        tool_input_namespaced = {"A": {"question_type": "yes_no"}}
        tool_input_flat = flatten_observe_context(tool_input_namespaced)

        # Tool uses the flat field and includes it in output
        tool_output = {"question_type": tool_input_flat["question_type"], "summary": "42"}

        # Downstream LLM action observes tool's output
        field_context = {"tool_b": tool_output}
        _, llm_ctx, _ = apply_context_scope(
            field_context,
            {"observe": ["tool_b.question_type", "tool_b.summary"]},
            action_name="downstream_llm",
        )
        assert llm_ctx["tool_b"]["question_type"] == "yes_no"
        assert llm_ctx["tool_b"]["summary"] == "42"

    def test_without_flatten_downstream_breaks(self):
        """Without flatten, tool passes namespaced fields → downstream observe fails."""
        # Tool received namespaced input (old behavior) and passed it through
        tool_output_namespaced = {"A": {"question_type": "yes_no"}, "summary": "42"}
        field_context = {"tool_b": tool_output_namespaced}

        # question_type is nested under "A" — downstream can't find it directly
        _, llm_ctx, _ = apply_context_scope(
            field_context,
            {"observe": ["tool_b.summary"]},
            action_name="downstream_llm",
        )
        assert llm_ctx["tool_b"]["summary"] == "42"

        # But observe: ["tool_b.question_type"] would fail because it's under "A"
        from agent_actions.errors import ConfigurationError

        with pytest.raises(ConfigurationError):
            apply_context_scope(
                field_context,
                {"observe": ["tool_b.question_type"]},
                action_name="downstream_llm",
            )


# ---------------------------------------------------------------------------
# 5. File-mode observe — tool UDF
# ---------------------------------------------------------------------------


class TestFileModeObserveToolUdf:
    """apply_observe_for_file_mode handles normalized tool output."""

    def test_file_mode_observe_flat_content(self):
        """File-mode observe filter already produces flat content — verify."""
        from agent_actions.prompt.context.scope_file_mode import (
            apply_observe_for_file_mode,
        )

        data = [
            {
                "content": {"question_type": "yes_no", "confidence": 0.95},
                "source_guid": "sg-1",
                "node_id": "upstream_abc",
                "lineage": ["upstream_abc"],
            },
        ]
        agent_config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.question_type"]},
        }

        filtered = apply_observe_for_file_mode(
            data=data,
            agent_config=agent_config,
            agent_name="tool_b",
            agent_indices={"upstream": 0, "tool_b": 1},
            file_path="/tmp/test.json",
        )

        content = filtered[0].get("content", filtered[0])
        # Field is flat in content, not nested under a namespace key
        assert "question_type" in content
        assert content["question_type"] == "yes_no"


# ---------------------------------------------------------------------------
# 6. Security — drop still works
# ---------------------------------------------------------------------------


class TestDropStillWorks:
    """Dropping a field on a tool UDF action prevents observe leakage."""

    def test_drop_prevents_observe(self):
        """Dropped field is removed even when tool output is flat."""
        field_context = {
            "tool": {"api_key": "secret", "summary": "safe_data"},
        }
        _, llm_ctx, _ = apply_context_scope(
            field_context,
            {
                "drop": ["tool.api_key"],
                "observe": ["tool.*"],
            },
            action_name="downstream",
        )
        # api_key must NOT leak through wildcard observe
        assert "api_key" not in llm_ctx.get("tool", {})
        assert llm_ctx["tool"]["summary"] == "safe_data"

    def test_drop_on_flattened_context(self):
        """flatten_observe_context preserves all fields — drop is applied upstream."""
        # flatten itself doesn't drop; drop is handled by apply_context_scope
        namespaced = {"dep": {"api_key": "secret", "name": "test"}}
        flat = flatten_observe_context(namespaced)
        # flatten keeps everything (drop is responsibility of apply_context_scope)
        assert "api_key" in flat
        assert "name" in flat
