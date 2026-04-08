"""
Unit tests for LLMContextBuilder._build_llm_context.

These tests directly exercise the shared helper method to ensure consistent
behavior across edge cases. Integration tests verify end-to-end parity,
while these unit tests focus on the implementation details.
"""

from agent_actions.prompt.context.builder import LLMContextBuilder


class TestBuildLLMContextBasics:
    """Test basic merge and copy behavior."""

    def test_merges_additional_context(self):
        """Additional context should be merged into result."""
        base = {"base_key": "base_value"}
        additional = {"extra_key": "extra_value"}

        result = LLMContextBuilder._build_llm_context(base, additional, None)

        assert result["base_key"] == "base_value"
        assert result["extra_key"] == "extra_value"

    def test_additional_context_overwrites_base(self):
        """Additional context should overwrite base keys (update semantics)."""
        base = {"key": "original"}
        additional = {"key": "overwritten"}

        result = LLMContextBuilder._build_llm_context(base, additional, None)

        assert result["key"] == "overwritten"


class TestBuildLLMContextDropBehavior:
    """Test context_scope.drop behavior.

    Non-seed drops are enforced upstream by apply_context_scope (which
    removes fields from prompt_context before observe). The builder
    only handles seed drops.
    """

    def test_nonseed_drops_are_noop_in_builder(self):
        """Non-seed drops are handled upstream — builder passes them through."""
        base = {"keep": "this", "other": "stays"}
        context_scope = {"drop": ["source.other"]}

        result = LLMContextBuilder._build_llm_context(base, None, context_scope)

        # Builder does not drop non-seed fields — that's apply_context_scope's job
        assert "keep" in result
        assert "other" in result


class TestBuildLLMContextSeedDrops:
    """Test seed field drop behavior."""

    def test_drops_seed_field(self):
        """Seed fields should be dropped from nested seed dict."""
        base = {"seed": {"keep": "this", "secret": "drop_me"}}
        context_scope = {"drop": ["seed.secret"]}

        result = LLMContextBuilder._build_llm_context(base, None, context_scope)

        assert "seed" in result
        assert result["seed"]["keep"] == "this"
        assert "secret" not in result["seed"]

    def test_drops_multiple_seed_fields(self):
        """Multiple seed drops should all be applied."""
        base = {"seed": {"keep": "this", "drop1": "a", "drop2": "b"}}
        context_scope = {"drop": ["seed.drop1", "seed.drop2"]}

        result = LLMContextBuilder._build_llm_context(base, None, context_scope)

        assert result["seed"] == {"keep": "this"}

    def test_seed_removed_when_empty_after_drops(self):
        """Seed dict should be removed entirely if all fields dropped."""
        base = {"other": "keep", "seed": {"only_field": "value"}}
        context_scope = {"drop": ["seed.only_field"]}

        result = LLMContextBuilder._build_llm_context(base, None, context_scope)

        assert "other" in result
        assert "seed" not in result

    def test_seed_dict_not_mutated(self):
        """Original seed dict should not be mutated."""
        seed_data = {"secret": "value", "keep": "this"}
        base = {"seed": seed_data}
        context_scope = {"drop": ["seed.secret"]}

        LLMContextBuilder._build_llm_context(base, None, context_scope)

        # Original seed_data should be unchanged
        assert "secret" in seed_data
        assert seed_data == {"secret": "value", "keep": "this"}


class TestBuildLLMContextMixedDrops:
    """Test mixed seed and non-seed drops."""

    def test_mixed_seed_and_nonseed_drops(self):
        """Seed drops applied, non-seed drops pass through (handled upstream)."""
        base = {
            "top_level_keep": "stays",
            "keep": "this",
            "seed": {"seed_drop": "remove", "seed_keep": "this"},
        }
        context_scope = {"drop": ["source.top_level_keep", "seed.seed_drop"]}

        result = LLMContextBuilder._build_llm_context(base, None, context_scope)

        # Non-seed field stays (upstream responsibility)
        assert "top_level_keep" in result
        assert result["keep"] == "this"
        assert "seed_drop" not in result["seed"]
        assert result["seed"]["seed_keep"] == "this"


class TestBuildLLMContextBaseContextEdgeCases:
    """Test edge cases for base_context parameter."""

    def test_non_dict_base_context_returns_empty(self):
        """Non-dict base_context should return empty dict."""
        result = LLMContextBuilder._build_llm_context("not a dict", None, None)
        assert result == {}

    def test_none_base_context_returns_empty(self):
        """None base_context should return empty dict."""
        result = LLMContextBuilder._build_llm_context(None, None, None)
        assert result == {}

    def test_empty_base_context(self):
        """Empty base_context should work correctly."""
        result = LLMContextBuilder._build_llm_context({}, {"extra": "value"}, None)
        assert result == {"extra": "value"}


class TestPublicMethodDelegation:
    """Test that public methods correctly delegate to _build_llm_context."""

    def test_batch_delegates_correctly(self):
        """build_llm_context_for_batch should produce same result as _build_llm_context."""
        base = {"key": "value"}
        additional = {"extra": "data"}
        context_scope = {"drop": ["source.key"]}

        batch_result = LLMContextBuilder.build_llm_context_for_batch(
            base, additional, context_scope
        )
        direct_result = LLMContextBuilder._build_llm_context(base, additional, context_scope)

        assert batch_result == direct_result

    def test_online_delegates_correctly(self):
        """build_llm_context_for_online should produce same result as _build_llm_context."""
        base = {"key": "value"}
        additional = {"extra": "data"}
        context_scope = {"drop": ["source.key"]}

        online_result = LLMContextBuilder.build_llm_context_for_online(
            base, additional, context_scope
        )
        direct_result = LLMContextBuilder._build_llm_context(base, additional, context_scope)

        assert online_result == direct_result

    def test_online_passthrough_for_non_dict(self):
        """Online mode should pass through non-dict input unchanged."""
        result = LLMContextBuilder.build_llm_context_for_online("not a dict", {}, None)
        assert result == "not a dict"
