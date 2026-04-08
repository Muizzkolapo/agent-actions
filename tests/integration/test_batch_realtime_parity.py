"""
Batch vs Online context parity tests.

These tests ensure that batch and online modes produce identical context
for the same input, preventing divergence bugs where templates work in one
mode but fail in another.

ARCHITECTURE INVARIANT: Both modes MUST use PromptPreparationService as the
single source of truth for context building. These tests act as a regression
gate to catch any divergence.

See: https://github.com/Muizzkolapo/agent-actions/issues/640
"""

from typing import Any

import pytest

from agent_actions.prompt.service import (
    PromptPreparationService,
)


class TestPromptPreparationParity:
    """Verify batch and online produce identical prompt context."""

    def test_same_formatted_prompt_for_same_input(
        self,
        parity_agent_config_no_context_scope,
        parity_contents,
        parity_current_item,
        parity_agent_indices,
        parity_dependency_configs,
    ):
        """
        Both modes should format prompts identically.

        The formatted_prompt is the rendered Jinja2 template with all field
        references resolved. This MUST be identical across modes.
        """
        common_args = {
            "agent_config": parity_agent_config_no_context_scope,
            "agent_name": "parity_test_agent_simple",
            "contents": parity_contents,
            "agent_indices": parity_agent_indices,
            "dependency_configs": parity_dependency_configs,
            "source_content": parity_contents,
            "current_item": parity_current_item,
        }

        # Act: Call with mode="batch" and mode="online"
        batch_result = PromptPreparationService.prepare_prompt_with_context(
            mode="batch", **common_args
        )
        online_result = PromptPreparationService.prepare_prompt_with_context(
            mode="online", **common_args
        )

        # Assert: formatted_prompt must be identical
        assert batch_result.formatted_prompt == online_result.formatted_prompt, (
            f"Formatted prompts diverged!\n"
            f"Batch: {batch_result.formatted_prompt}\n"
            f"Online: {online_result.formatted_prompt}"
        )

    def test_same_prompt_context_for_same_input(
        self,
        parity_agent_config_no_context_scope,
        parity_contents,
        parity_current_item,
        parity_agent_indices,
        parity_dependency_configs,
    ):
        """
        Both modes should build identical prompt_context.

        prompt_context is the full context dict used for Jinja2 template
        rendering. It includes source, upstream actions, seed data, etc.
        This MUST be identical across modes.
        """
        common_args = {
            "agent_config": parity_agent_config_no_context_scope,
            "agent_name": "parity_test_agent_simple",
            "contents": parity_contents,
            "agent_indices": parity_agent_indices,
            "dependency_configs": parity_dependency_configs,
            "source_content": parity_contents,
            "current_item": parity_current_item,
        }

        batch_result = PromptPreparationService.prepare_prompt_with_context(
            mode="batch", **common_args
        )
        online_result = PromptPreparationService.prepare_prompt_with_context(
            mode="online", **common_args
        )

        # Assert: prompt_context must be identical
        assert batch_result.prompt_context == online_result.prompt_context, (
            f"Prompt contexts diverged!\n"
            f"Batch keys: {set(batch_result.prompt_context.keys()) if batch_result.prompt_context else 'None'}\n"
            f"Online keys: {set(online_result.prompt_context.keys()) if online_result.prompt_context else 'None'}"
        )

    def test_same_passthrough_fields(
        self,
        parity_agent_config,
        parity_contents,
        parity_current_item,
        parity_agent_indices,
        parity_dependency_configs,
    ):
        """
        Both modes should extract identical passthrough fields.

        Passthrough fields (from context_scope.passthrough) are extracted
        for merging into output. Must be identical across modes.
        """
        common_args = {
            "agent_config": parity_agent_config,
            "agent_name": "parity_test_agent",
            "contents": parity_contents,
            "agent_indices": parity_agent_indices,
            "dependency_configs": parity_dependency_configs,
            "source_content": parity_contents,
            "current_item": parity_current_item,
        }

        batch_result = PromptPreparationService.prepare_prompt_with_context(
            mode="batch", **common_args
        )
        online_result = PromptPreparationService.prepare_prompt_with_context(
            mode="online", **common_args
        )

        # Assert: passthrough_fields must be identical
        assert batch_result.passthrough_fields == online_result.passthrough_fields, (
            f"Passthrough fields diverged!\n"
            f"Batch: {batch_result.passthrough_fields}\n"
            f"Online: {online_result.passthrough_fields}"
        )

    def test_metadata_records_correct_mode(
        self,
        parity_agent_config_no_context_scope,
        parity_contents,
        parity_current_item,
        parity_agent_indices,
        parity_dependency_configs,
    ):
        """
        Metadata should correctly record the mode used.

        This ensures traceability for debugging which mode was used.
        """
        common_args = {
            "agent_config": parity_agent_config_no_context_scope,
            "agent_name": "parity_test_agent_simple",
            "contents": parity_contents,
            "agent_indices": parity_agent_indices,
            "dependency_configs": parity_dependency_configs,
            "source_content": parity_contents,
            "current_item": parity_current_item,
        }

        batch_result = PromptPreparationService.prepare_prompt_with_context(
            mode="batch", **common_args
        )
        online_result = PromptPreparationService.prepare_prompt_with_context(
            mode="online", **common_args
        )

        # Assert: mode is recorded in metadata
        assert batch_result.metadata.get("mode") == "batch"
        assert online_result.metadata.get("mode") == "online"


class TestPromptPreparationParityWithContextScope:
    """Verify parity holds across various context_scope configurations."""

    @pytest.mark.parametrize(
        "context_scope_config,description",
        [
            (
                {"observe": ["source.text", "source.metadata"]},
                "observe only",
            ),
            (
                {"observe": ["source.text"], "drop": ["source.internal_id"]},
                "drop only",
            ),
            (
                {"observe": ["source.text"], "passthrough": ["source.record_id"]},
                "passthrough only",
            ),
            (
                {
                    "observe": ["source.text", "source.metadata"],
                    "drop": ["source.internal_id"],
                },
                "observe and drop",
            ),
            (
                {
                    "observe": ["source.text", "source.metadata"],
                    "drop": ["source.internal_id"],
                    "passthrough": ["source.record_id"],
                },
                "all directives",
            ),
        ],
    )
    def test_parity_with_context_scope_config(
        self,
        context_scope_config: dict[str, Any],
        description: str,
        parity_contents,
        parity_current_item,
        parity_agent_indices,
        parity_dependency_configs,
    ):
        """
        Parity holds across observe/drop/passthrough configurations.

        Tests that various combinations of context_scope directives
        produce identical results in both modes.
        """
        agent_config = {
            "name": "parity_test_agent",
            "agent_type": "llm_agent",
            "model_vendor": "mock",
            "model_name": "mock-model",
            "json_mode": True,
            "prompt": "Process: {{ source.text }}",
            "context_scope": context_scope_config,
        }

        common_args = {
            "agent_config": agent_config,
            "agent_name": "parity_test_agent",
            "contents": parity_contents,
            "agent_indices": parity_agent_indices,
            "dependency_configs": parity_dependency_configs,
            "source_content": parity_contents,
            "current_item": parity_current_item,
        }

        batch_result = PromptPreparationService.prepare_prompt_with_context(
            mode="batch", **common_args
        )
        online_result = PromptPreparationService.prepare_prompt_with_context(
            mode="online", **common_args
        )

        # Assert: formatted_prompt must be identical
        assert batch_result.formatted_prompt == online_result.formatted_prompt, (
            f"Formatted prompts diverged with {description}!\n"
            f"Batch: {batch_result.formatted_prompt}\n"
            f"Online: {online_result.formatted_prompt}"
        )

        # Assert: prompt_context must be identical
        assert batch_result.prompt_context == online_result.prompt_context, (
            f"Prompt contexts diverged with {description}!"
        )

        # Assert: passthrough_fields must be identical
        assert batch_result.passthrough_fields == online_result.passthrough_fields, (
            f"Passthrough fields diverged with {description}!"
        )


class TestLLMContextDifferences:
    """
    Document and verify legitimate llm_context differences between modes.

    LLMContextBuilder has mode-specific implementations for backward
    compatibility. These tests document what differences are expected
    and ensure they are semantically equivalent.
    """

    def test_llm_context_drop_behavior_documented(
        self,
        parity_agent_config,
        parity_contents,
        parity_current_item,
        parity_agent_indices,
        parity_dependency_configs,
    ):
        """
        Document that llm_context may differ slightly between modes.

        Batch uses dict.pop() for drops, online uses DataTransformer.
        Both should produce semantically equivalent results (dropped fields
        are absent), but implementation details may cause minor differences.
        """
        common_args = {
            "agent_config": parity_agent_config,
            "agent_name": "parity_test_agent",
            "contents": parity_contents,
            "agent_indices": parity_agent_indices,
            "dependency_configs": parity_dependency_configs,
            "source_content": parity_contents,
            "current_item": parity_current_item,
        }

        batch_result = PromptPreparationService.prepare_prompt_with_context(
            mode="batch", **common_args
        )
        online_result = PromptPreparationService.prepare_prompt_with_context(
            mode="online", **common_args
        )

        # Document: llm_context exists in both
        assert batch_result.llm_context is not None
        assert online_result.llm_context is not None

        # Both should have dropped 'internal_id' (from context_scope.drop)
        batch_source = batch_result.llm_context.get("source", {})
        online_source = online_result.llm_context.get("source", {})

        assert "internal_id" not in batch_source, "Batch should have dropped 'internal_id'"
        assert "internal_id" not in online_source, "Online should have dropped 'internal_id'"

        # Both should have observed 'metadata' (from context_scope.observe)
        assert "metadata" in batch_source, "Batch should have observed 'metadata'"
        assert "metadata" in online_source, "Online should have observed 'metadata'"


class TestEdgeCases:
    """Edge case tests for parity behavior."""

    def test_empty_contents_parity(
        self,
        parity_agent_config_no_context_scope,
        parity_current_item,
        parity_agent_indices,
        parity_dependency_configs,
    ):
        """Both modes should handle empty contents identically."""
        common_args = {
            "agent_config": parity_agent_config_no_context_scope,
            "agent_name": "parity_test_agent_simple",
            "contents": {},
            "agent_indices": parity_agent_indices,
            "dependency_configs": parity_dependency_configs,
            "current_item": parity_current_item,
        }

        batch_result = PromptPreparationService.prepare_prompt_with_context(
            mode="batch", **common_args
        )
        online_result = PromptPreparationService.prepare_prompt_with_context(
            mode="online", **common_args
        )

        # Assert: Both should handle empty contents without error
        assert batch_result.formatted_prompt == online_result.formatted_prompt

    def test_none_optional_params_parity(
        self,
        parity_agent_config_no_context_scope,
        parity_contents,
    ):
        """Both modes should handle None optional params identically.

        source_content is required so the observed source.text field exists
        at runtime. Other optional params remain None.
        """
        common_args = {
            "agent_config": parity_agent_config_no_context_scope,
            "agent_name": "parity_test_agent_simple",
            "contents": parity_contents,
            "source_content": parity_contents,
            # Other optional params default to None
        }

        batch_result = PromptPreparationService.prepare_prompt_with_context(
            mode="batch", **common_args
        )
        online_result = PromptPreparationService.prepare_prompt_with_context(
            mode="online", **common_args
        )

        assert batch_result.formatted_prompt == online_result.formatted_prompt

    def test_no_context_scope_raises_error(
        self,
        parity_contents,
        parity_current_item,
        parity_agent_indices,
        parity_dependency_configs,
    ):
        """Missing context_scope must raise ConfigurationError in both modes."""
        from agent_actions.errors import ConfigurationError

        agent_config = {
            "name": "no_scope_agent",
            "agent_type": "llm_agent",
            "model_vendor": "mock",
            "model_name": "mock-model",
            "json_mode": True,
            "prompt": "Simple prompt with {{ source.text }}",
            # No context_scope defined
        }

        common_args = {
            "agent_config": agent_config,
            "agent_name": "no_scope_agent",
            "contents": parity_contents,
            "agent_indices": parity_agent_indices,
            "dependency_configs": parity_dependency_configs,
            "source_content": parity_contents,
            "current_item": parity_current_item,
        }

        with pytest.raises(ConfigurationError, match="context_scope is required"):
            PromptPreparationService.prepare_prompt_with_context(mode="batch", **common_args)

        with pytest.raises(ConfigurationError, match="context_scope is required"):
            PromptPreparationService.prepare_prompt_with_context(mode="online", **common_args)
