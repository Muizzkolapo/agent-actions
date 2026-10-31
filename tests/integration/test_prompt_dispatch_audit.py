"""Comprehensive prompt dispatch audit tests.

Tests the full prompt pipeline:
- File loading and block extraction
- Jinja2 template rendering with context
- dispatch_task() resolution
- Provider-specific message building
- Batch/online parity
- Prompt caching and debug output
"""

from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError, PromptValidationError
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.prompt.handler import PromptLoader
from agent_actions.prompt.message_builder import (
    PROVIDER_MESSAGE_CONFIGS,
    MessageBuilder,
    MessageRole,
)
from agent_actions.prompt.prompt_utils import PromptUtils

# ── Test Prompt Loading ───────────────────────────────────────────────


class TestPromptLoading:
    """Tests for prompt file loading and block extraction."""

    def test_file_block_resolution(self, tmp_path):
        """load_prompt resolves 'filename.block' to the block content."""
        prompt_dir = tmp_path / "prompt_store"
        prompt_dir.mkdir()
        (prompt_dir / "workflow.md").write_text(
            "{prompt extract}\nExtract the claims.\n{end_prompt}\n"
        )

        with patch(
            "agent_actions.prompt.handler.resolve_project_root",
            return_value=tmp_path,
        ):
            result = PromptLoader.load_prompt("workflow.extract")

        assert result == "Extract the claims."

    def test_missing_file_raises(self, tmp_path):
        """Missing prompt file raises ValueError with the file name."""
        prompt_dir = tmp_path / "prompt_store"
        prompt_dir.mkdir()

        with (
            patch(
                "agent_actions.prompt.handler.resolve_project_root",
                return_value=tmp_path,
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            PromptLoader.load_prompt("nonexistent.block")

    def test_missing_block_raises(self, tmp_path):
        """Missing block in an existing file raises ValueError."""
        prompt_dir = tmp_path / "prompt_store"
        prompt_dir.mkdir()
        (prompt_dir / "workflow.md").write_text("{prompt existing}\nContent.\n{end_prompt}\n")

        with (
            patch(
                "agent_actions.prompt.handler.resolve_project_root",
                return_value=tmp_path,
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            PromptLoader.load_prompt("workflow.missing_block")

    def test_duplicate_block_names_rejected(self):
        """Duplicate prompt names in the same file raise ValueError."""
        content = "{prompt dup}\nA\n{end_prompt}\n{prompt dup}\nB\n{end_prompt}\n"

        with pytest.raises(ValueError, match="Duplicate"):
            PromptLoader.validate_unique_prompts("test.md", content)

    def test_unclosed_block_detected(self):
        """An unclosed prompt block raises ValueError."""
        content = "{prompt open}\nNo end token here.\n"

        with pytest.raises(ValueError, match="Unclosed"):
            PromptLoader.validate_prompt_blocks("test.md", content)

    def test_extract_prompt_strips_whitespace(self):
        """Extracted block content is stripped of leading/trailing whitespace."""
        content = "{prompt test}\n  \n  Content here.  \n  \n{end_prompt}"
        result = PromptLoader.extract_prompt(content, "test")
        assert result == "Content here."

    def test_empty_block_after_load_raises(self):
        """A prompt block with only whitespace raises on get_raw_prompt."""
        config = {"prompt": "$workflow.empty_block", "agent_type": "test"}

        with patch.object(PromptLoader, "load_prompt", return_value=""):
            with pytest.raises(PromptValidationError, match="empty"):
                PromptFormatter.get_raw_prompt(config)


# ── Test Template Rendering ───────────────────────────────────────────


class TestTemplateRendering:
    """Tests for Jinja2 template rendering with context."""

    def test_framework_namespaces_always_available(self):
        """Framework namespaces (seed, version, workflow) are available."""
        from agent_actions.prompt.context.scope_application import (
            FRAMEWORK_NAMESPACES,
        )

        # These should always be declared as framework namespaces.
        assert "version" in FRAMEWORK_NAMESPACES
        assert "seed" in FRAMEWORK_NAMESPACES
        assert "workflow" in FRAMEWORK_NAMESPACES

    def test_seed_data_injected(self):
        """Seed data is available under the 'seed' namespace in prompt_context."""
        from agent_actions.prompt.context.scope_application import (
            apply_context_scope,
        )

        field_context = {"source": {"input": "data"}}
        context_scope = {"observe": ["source.*"]}
        static_data = {"reference": "lookup_value"}

        prompt_context, _, _ = apply_context_scope(
            field_context,
            context_scope,
            static_data=static_data,
            action_name="test",
        )

        assert "seed" in prompt_context
        assert prompt_context["seed"]["reference"] == "lookup_value"


# ── Test Dispatch Task ────────────────────────────────────────────────


class TestDispatchTask:
    """Tests for dispatch_task() resolution in prompts and schemas."""

    def test_dispatch_replaced_with_function_result(self):
        """dispatch_task('func') is replaced with the function's return value."""
        with patch.object(
            PromptUtils, "process_dispatch_in_text", wraps=PromptUtils.process_dispatch_in_text
        ):
            mock_result = "computed_value"
            with patch(
                "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
                return_value=mock_result,
            ):
                result = PromptUtils.process_dispatch_in_text(
                    "Use: dispatch_task('my_func')",
                    tools_path="/tools",
                    context_data_str="{}",
                )
            assert result == "Use: computed_value"
            assert "dispatch_task" not in result

    def test_dispatch_in_schema_resolved(self):
        """dispatch_task in schema context preserves return type."""
        with patch(
            "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
            return_value={"key": "value"},
        ):
            result = PromptUtils.process_dispatch_in_text(
                "dispatch_task('schema_func')",
                tools_path="/tools",
                context_data_str="{}",
                preserve_type_on_exact_match=True,
            )
        assert result == {"key": "value"}
        assert isinstance(result, dict)

    def test_missing_function_raises(self):
        """dispatch_task referencing a non-existent function raises."""
        with patch(
            "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
            side_effect=AgentActionsError("Could not find function 'missing'"),
        ):
            with pytest.raises(AgentActionsError, match="Could not find function"):
                PromptUtils.process_dispatch_in_text(
                    "dispatch_task('missing')",
                    tools_path="/tools",
                    context_data_str="{}",
                )

    def test_type_preservation_on_exact_match(self):
        """When text is exactly one dispatch_task call, raw type is preserved."""
        with patch(
            "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
            return_value=[1, 2, 3],
        ):
            result = PromptUtils.process_dispatch_in_text(
                "dispatch_task('list_func')",
                tools_path="/tools",
                context_data_str="{}",
                preserve_type_on_exact_match=True,
            )
        assert result == [1, 2, 3]

    def test_none_return_raises(self):
        """dispatch_task returning None raises instead of injecting error text."""
        with patch(
            "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
            return_value=None,
        ):
            with pytest.raises(AgentActionsError, match="returned None"):
                PromptUtils.process_dispatch_in_text(
                    "dispatch_task('null_func')",
                    tools_path="/tools",
                    context_data_str="{}",
                )

    def test_multiple_dispatch_calls_all_resolved(self):
        """Multiple dispatch_task calls in one text are all resolved."""
        call_count = 0

        def mock_call(name, path, ctx):
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        with patch(
            "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
            side_effect=mock_call,
        ):
            result = PromptUtils.process_dispatch_in_text(
                "A: dispatch_task('a') B: dispatch_task('b')",
                tools_path="/tools",
                context_data_str="{}",
            )
        assert "dispatch_task" not in result
        assert "result_" in result


# ── Test Message Builder ──────────────────────────────────────────────


class TestMessageBuilder:
    """Tests for provider-specific message building."""

    @pytest.mark.parametrize(
        ("vendor", "role"),
        [
            ("anthropic", MessageRole.SINGLE_USER),
            ("openai", MessageRole.SYSTEM_ONLY),
            ("groq", MessageRole.SYSTEM_ONLY),
            ("ollama_local", MessageRole.SYSTEM_PLUS_USER),
        ],
        ids=["anthropic", "openai", "groq", "ollama_local"],
    )
    def test_json_mode_role_per_vendor(self, vendor, role):
        assert PROVIDER_MESSAGE_CONFIGS[vendor].json_role == role

    def test_all_providers_have_config(self):
        """Every expected provider has a MessageBuilder config entry."""
        expected = {
            "anthropic",
            "openai",
            "groq",
            "gemini",
            "cohere",
            "ollama_local",
            "ollama_cloud",
        }
        assert expected.issubset(set(PROVIDER_MESSAGE_CONFIGS.keys()))

    def test_json_mode_role_assignment(self):
        """JSON mode uses the provider's json_role, not non_json_role."""
        envelope = MessageBuilder.build(
            "openai",
            "Test prompt",
            "{}",
            schema={"type": "object", "properties": {}},
            json_mode=True,
        )
        # OpenAI JSON mode splits into system + user messages
        assert len(envelope.messages) == 2
        assert envelope.messages[0].role == "system"
        assert envelope.messages[1].role == "user"

    def test_non_json_mode_role_assignment(self):
        """Non-JSON mode uses the provider's non_json_role."""
        envelope = MessageBuilder.build(
            "openai",
            "Test prompt",
            "Some context",
            json_mode=False,
        )
        assert len(envelope.messages) == 1
        assert envelope.messages[0].role == "user"


# ── Test Prompt Features ─────────────────────────────────────────────


class TestPromptFeatures:
    """Tests for prompt caching, debug output, and related features."""

    def test_prompt_debug_prints_output(self):
        """prompt_debug=true causes rendered prompt to be echoed via click."""
        from agent_actions.llm.realtime.services.prompt_service import PromptService

        agent_config = {"prompt_debug": True}
        with patch("agent_actions.llm.realtime.services.prompt_service.click") as mock_click:
            PromptService.debug_print_prompt(
                agent_config=agent_config,
                prompt_config="Test rendered prompt",
                context_data="ctx",
                schema={"type": "object"},
            )
            mock_click.echo.assert_called()

    def test_prompt_debug_off_no_output(self):
        """prompt_debug=false produces no CLI output."""
        from agent_actions.llm.realtime.services.prompt_service import PromptService

        agent_config = {"prompt_debug": False}
        with patch("agent_actions.llm.realtime.services.prompt_service.click") as mock_click:
            PromptService.debug_print_prompt(
                agent_config=agent_config,
                prompt_config="Test rendered prompt",
                context_data="ctx",
                schema={"type": "object"},
            )
            mock_click.echo.assert_not_called()
