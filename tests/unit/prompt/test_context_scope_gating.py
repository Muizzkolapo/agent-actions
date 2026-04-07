"""Tests for context_scope data gating.

Verifies that context_scope is the sole gate for data access:
- observe fields → prompt_context + llm_context
- passthrough fields → prompt_context + output (not llm_context)
- drop fields → removed from everything
- framework namespaces (version, seed, workflow, loop) → always in prompt_context
- no context_scope → hard error
"""

import pytest

from agent_actions.prompt.context.scope_application import (
    FRAMEWORK_NAMESPACES,
    apply_context_scope,
)


class TestLLMContextGating:
    """Verify llm_context contains only observe fields."""

    def test_observe_fields_in_llm_context(self):
        """Only observed fields should appear in llm_context."""
        field_context = {
            "source": {"text": "hello", "secret": "hidden"},
            "dep": {"score": 0.9, "debug": "internal"},
        }
        context_scope = {"observe": ["source.text", "dep.score"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope)

        assert llm_context == {"text": "hello", "score": 0.9}

    def test_passthrough_fields_not_in_llm_context(self):
        """Passthrough fields must NOT appear in llm_context."""
        field_context = {"source": {"text": "hello", "id": "rec-1"}}
        context_scope = {
            "observe": ["source.text"],
            "passthrough": ["source.id"],
        }

        _, llm_context, passthrough = apply_context_scope(field_context, context_scope)

        assert "text" in llm_context
        assert "id" not in llm_context
        assert passthrough["id"] == "rec-1"

    def test_empty_observe_produces_empty_llm_context(self):
        """Empty observe list should produce empty llm_context (not an error)."""
        field_context = {"source": {"text": "hello"}}
        context_scope = {"passthrough": ["source.text"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope)

        assert llm_context == {}

    def test_wildcard_observe_includes_all_namespace_fields(self):
        """observe: [dep.*] should include all fields from the namespace."""
        field_context = {"dep": {"field1": "a", "field2": "b", "field3": "c"}}
        context_scope = {"observe": ["dep.*"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope)

        assert llm_context == {"field1": "a", "field2": "b", "field3": "c"}


class TestPromptContextGating:
    """Verify prompt_context contains only observe + passthrough + framework namespaces."""

    def test_only_observed_fields_in_prompt_context(self):
        """prompt_context should only have fields from observe."""
        field_context = {
            "source": {"text": "hello", "secret": "hidden"},
        }
        context_scope = {"observe": ["source.text"]}

        prompt_context, _, _ = apply_context_scope(field_context, context_scope)

        assert "source" in prompt_context
        assert prompt_context["source"] == {"text": "hello"}
        assert "secret" not in prompt_context["source"]

    def test_passthrough_fields_in_prompt_context(self):
        """Passthrough fields should be accessible in prompt_context."""
        field_context = {"source": {"text": "hello", "name": "product"}}
        context_scope = {
            "observe": ["source.text"],
            "passthrough": ["source.name"],
        }

        prompt_context, _, _ = apply_context_scope(field_context, context_scope)

        assert prompt_context["source"]["text"] == "hello"
        assert prompt_context["source"]["name"] == "product"

    def test_unscoped_namespace_excluded_from_prompt_context(self):
        """Namespaces not in observe or passthrough are excluded."""
        field_context = {
            "source": {"text": "hello"},
            "unscoped_dep": {"data": "should not be here"},
        }
        context_scope = {"observe": ["source.text"]}

        prompt_context, _, _ = apply_context_scope(field_context, context_scope)

        assert "source" in prompt_context
        assert "unscoped_dep" not in prompt_context

    def test_wildcard_observe_preserves_full_namespace(self):
        """observe: [dep.*] should keep all fields from dep in prompt_context."""
        field_context = {"dep": {"a": 1, "b": 2, "c": 3}}
        context_scope = {"observe": ["dep.*"]}

        prompt_context, _, _ = apply_context_scope(field_context, context_scope)

        assert prompt_context["dep"] == {"a": 1, "b": 2, "c": 3}

    def test_drop_removes_from_prompt_context(self):
        """Dropped fields must not appear in prompt_context even if observed."""
        field_context = {"dep": {"public": "ok", "secret": "hidden"}}
        context_scope = {
            "observe": ["dep.*"],
            "drop": ["dep.secret"],
        }

        prompt_context, llm_context, _ = apply_context_scope(field_context, context_scope)

        assert "secret" not in prompt_context.get("dep", {})
        assert "secret" not in llm_context
        assert prompt_context["dep"]["public"] == "ok"


class TestFrameworkNamespaces:
    """Verify framework namespaces are always available in prompt_context."""

    def test_version_namespace_always_available(self):
        """version namespace should always be in prompt_context."""
        field_context = {
            "source": {"text": "hello"},
            "version": {"i": 1, "idx": 0, "length": 3, "first": True, "last": False},
        }
        context_scope = {"observe": ["source.text"]}

        prompt_context, _, _ = apply_context_scope(field_context, context_scope)

        assert "version" in prompt_context
        assert prompt_context["version"]["i"] == 1
        assert prompt_context["version"]["length"] == 3

    def test_seed_namespace_always_available(self):
        """seed namespace should always be in prompt_context."""
        field_context = {"source": {"text": "hello"}}
        static_data = {"rubric": {"criteria": "test"}}
        context_scope = {"observe": ["source.text"]}

        prompt_context, _, _ = apply_context_scope(
            field_context, context_scope, static_data=static_data
        )

        assert "seed" in prompt_context
        assert prompt_context["seed"]["rubric"]["criteria"] == "test"

    def test_workflow_namespace_always_available(self):
        """workflow namespace should always be in prompt_context."""
        field_context = {
            "source": {"text": "hello"},
            "workflow": {"name": "test_workflow", "version": "1.0"},
        }
        context_scope = {"observe": ["source.text"]}

        prompt_context, _, _ = apply_context_scope(field_context, context_scope)

        assert "workflow" in prompt_context
        assert prompt_context["workflow"]["name"] == "test_workflow"

    def test_framework_namespaces_not_in_llm_context(self):
        """Framework namespaces should not leak into llm_context."""
        field_context = {
            "source": {"text": "hello"},
            "version": {"i": 1},
            "workflow": {"name": "test"},
        }
        context_scope = {"observe": ["source.text"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope)

        assert "version" not in llm_context
        assert "workflow" not in llm_context
        assert llm_context == {"text": "hello"}

    def test_framework_namespaces_constant_matches_expected(self):
        """FRAMEWORK_NAMESPACES should contain exactly the expected namespaces."""
        assert FRAMEWORK_NAMESPACES == frozenset({"version", "seed", "workflow", "loop"})


class TestHardErrorOnMissingContextScope:
    """Verify hard error when context_scope is missing at the service layer."""

    def test_build_llm_context_raises_without_context_scope(self):
        """_build_llm_context should raise ConfigurationError when no context_scope."""
        from agent_actions.errors import ConfigurationError
        from agent_actions.prompt.service import PromptPreparationService

        with pytest.raises(ConfigurationError, match="context_scope is required"):
            PromptPreparationService._build_llm_context(
                mode="online",
                contents={"text": "hello"},
                llm_additional_context={},
                context_scope=None,
            )

    def test_build_llm_context_raises_with_empty_context_scope(self):
        """Empty dict context_scope should also raise."""
        from agent_actions.errors import ConfigurationError
        from agent_actions.prompt.service import PromptPreparationService

        with pytest.raises(ConfigurationError, match="context_scope is required"):
            PromptPreparationService._build_llm_context(
                mode="online",
                contents={"text": "hello"},
                llm_additional_context={},
                context_scope={},
            )

    def test_build_llm_context_works_with_context_scope(self):
        """Valid context_scope should not raise."""
        from agent_actions.prompt.service import PromptPreparationService

        result = PromptPreparationService._build_llm_context(
            mode="online",
            contents={"text": "hello"},
            llm_additional_context={"observed": "value"},
            context_scope={"observe": ["source.text"]},
        )

        # Only observe fields — raw contents NOT included
        assert result == {"observed": "value"}
        assert "text" not in result

    def test_build_llm_context_raw_contents_never_in_result(self):
        """Even with context_scope, raw contents must not appear in llm_context."""
        from agent_actions.prompt.service import PromptPreparationService

        result = PromptPreparationService._build_llm_context(
            mode="batch",
            contents={"raw_field": "should not appear", "another": "also not"},
            llm_additional_context={"observed_field": "yes"},
            context_scope={"observe": ["source.observed_field"]},
        )

        assert "raw_field" not in result
        assert "another" not in result
        assert result["observed_field"] == "yes"
