"""Tests for non-JSON output standardization across all LLM providers.

Validates that every provider's call_non_json() returns List[Dict[str, str]]
with the correct output_field key, matching the BaseClient contract.

Also covers:
- Cohere call_json schema.keys() fix (compiled schema format + schema=None)
- compile_unified_schema for groq, mistral, cohere targets
- Ollama token count extraction
- Anthropic call_json return normalization
"""

import typing
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.output.response.schema import compile_unified_schema

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

SAMPLE_UNIFIED_SCHEMA = {
    "name": "test_schema",
    "description": "A test schema",
    "fields": [
        {"id": "name", "type": "string", "required": True},
        {"id": "age", "type": "integer", "required": False},
    ],
}


@pytest.fixture
def base_agent_config():
    """Minimal agent config for call_non_json tests."""
    return {"model_name": "test-model"}


@pytest.fixture
def agent_config_with_output_field():
    """Agent config with custom output_field."""
    return {"model_name": "test-model", "output_field": "summary"}


def _make_gemini_mocks(text):
    """Set up Gemini mock response for google-genai SDK."""
    mock_response = MagicMock()
    mock_response.text = text
    mock_response.usage_metadata = None
    return mock_response


def _make_openai_style_mocks(text, prompt_tokens=10, completion_tokens=5, total_tokens=15):
    """Build mock response for OpenAI-style providers (Groq, OpenAI)."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = text
    mock_response.usage.prompt_tokens = prompt_tokens
    mock_response.usage.completion_tokens = completion_tokens
    mock_response.usage.total_tokens = total_tokens
    return mock_response


def _make_mistral_mocks(text, prompt_tokens=20, completion_tokens=10, total_tokens=30):
    """Build mock response for Mistral (uses chat.complete instead of chat.completions.create)."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = text
    mock_response.usage.prompt_tokens = prompt_tokens
    mock_response.usage.completion_tokens = completion_tokens
    mock_response.usage.total_tokens = total_tokens
    return mock_response


def _make_cohere_mocks(text):
    """Build mock response for Cohere."""
    text_block = MagicMock()
    text_block.text = text
    mock_response = MagicMock()
    mock_response.message.content = [text_block]
    mock_response.usage = None
    return mock_response


def _make_anthropic_mocks(text, input_tokens=10, output_tokens=20):
    """Build mock response for Anthropic."""
    text_block = MagicMock()
    text_block.text = text
    mock_response = MagicMock()
    mock_response.content = [text_block]
    mock_response.usage.input_tokens = input_tokens
    mock_response.usage.output_tokens = output_tokens
    mock_response.stop_reason = "end_turn"
    return mock_response


# Provider setup functions for parameterized call_non_json tests.
# Each returns (patch_targets, setup_fn) where setup_fn takes the mocks and text,
# then returns the client class and its call_non_json method args.


def _setup_gemini(text):
    mock_response = _make_gemini_mocks(text)
    patches = {
        "fire": "agent_actions.llm.providers.gemini.client.fire_event",
        "mod": "agent_actions.llm.providers.gemini.client._build_client",
    }

    def configure(mock_mod, mock_fire):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_mod.return_value = mock_client

    from agent_actions.llm.providers.gemini.client import GeminiClient

    return patches, configure, GeminiClient


def _setup_groq(text):
    mock_response = _make_openai_style_mocks(text)
    patches = {
        "fire": "agent_actions.llm.providers.groq.client.fire_event",
        "mod": "agent_actions.llm.providers.groq.client.Groq",
    }

    def configure(mock_mod, mock_fire):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_mod.return_value = mock_client

    from agent_actions.llm.providers.groq.client import GroqClient

    return patches, configure, GroqClient


def _setup_mistral(text):
    mock_response = _make_mistral_mocks(text)
    patches = {
        "fire": "agent_actions.llm.providers.mistral.client.fire_event",
        "mod": "agent_actions.llm.providers.mistral.client.Mistral",
    }

    def configure(mock_mod, mock_fire):
        mock_client = MagicMock()
        mock_client.chat.complete.return_value = mock_response
        mock_mod.return_value = mock_client

    from agent_actions.llm.providers.mistral.client import MistralClient

    return patches, configure, MistralClient


def _setup_cohere(text):
    mock_response = _make_cohere_mocks(text)
    patches = {
        "fire": "agent_actions.llm.providers.cohere.client.fire_event",
        "mod": "agent_actions.llm.providers.cohere.client.cohere",
    }

    def configure(mock_mod, mock_fire):
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_mod.ClientV2.return_value = mock_client

    from agent_actions.llm.providers.cohere.client import CohereClient

    return patches, configure, CohereClient


def _setup_anthropic(text):
    mock_response = _make_anthropic_mocks(text)
    patches = {
        "fire": "agent_actions.llm.providers.anthropic.client.fire_event",
        "mod": "agent_actions.llm.providers.anthropic.client.anthropic",
    }

    def configure(mock_mod, mock_fire):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_mod.Anthropic.return_value = mock_client

    from agent_actions.llm.providers.anthropic.client import AnthropicClient

    return patches, configure, AnthropicClient


PROVIDER_SETUPS = [
    pytest.param("gemini", _setup_gemini, id="gemini"),
    pytest.param("groq", _setup_groq, id="groq"),
    pytest.param("mistral", _setup_mistral, id="mistral"),
    pytest.param("cohere", _setup_cohere, id="cohere"),
    pytest.param("anthropic", _setup_anthropic, id="anthropic"),
]


def _run_provider_call_non_json(setup_fn, text, config):
    """Execute call_non_json for any provider using its setup function."""
    patches_dict, configure, client_cls = setup_fn(text)
    with patch(patches_dict["fire"]) as mock_fire, patch(patches_dict["mod"]) as mock_mod:
        configure(mock_mod, mock_fire)
        return client_cls.call_non_json("key", config, "prompt", "data")


# ---------------------------------------------------------------------------
# Parameterized call_non_json: default field + custom output_field
# ---------------------------------------------------------------------------


class TestCallNonJsonReturnContract:
    """All providers' call_non_json returns List[Dict[str, str]] with correct field."""

    @pytest.mark.parametrize("provider_name,setup_fn", PROVIDER_SETUPS)
    def test_returns_list_of_dict_default_field(self, provider_name, setup_fn, base_agent_config):
        result = _run_provider_call_non_json(
            setup_fn, f"{provider_name} response", base_agent_config
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0] == {"raw_response": f"{provider_name} response"}

    @pytest.mark.parametrize("provider_name,setup_fn", PROVIDER_SETUPS)
    def test_returns_custom_output_field(
        self, provider_name, setup_fn, agent_config_with_output_field
    ):
        result = _run_provider_call_non_json(
            setup_fn, "Summary text", agent_config_with_output_field
        )

        assert result[0] == {"summary": "Summary text"}


# ---------------------------------------------------------------------------
# Gemini-specific: no JSON directives in non-JSON mode
# ---------------------------------------------------------------------------


class TestGeminiCallNonJson:
    @patch("agent_actions.llm.providers.gemini.client.fire_event")
    @patch("agent_actions.llm.providers.gemini.client._build_client")
    def test_no_json_directives_in_non_json_mode(
        self, mock_build_client, mock_fire, base_agent_config
    ):
        """Non-JSON mode must NOT pass JSON-forcing config to generate_content."""
        from agent_actions.llm.providers.gemini.client import GeminiClient

        mock_response = MagicMock()
        mock_response.text = "plain text"
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_build_client.return_value = mock_client

        GeminiClient.call_non_json("key", base_agent_config, "prompt", "data")

        call_kwargs = mock_client.models.generate_content.call_args[1]
        assert call_kwargs["model"] == "test-model"
        # Empty gen_params produces config=None (no JSON forcing)
        assert call_kwargs.get("config") is None


# ---------------------------------------------------------------------------
# Groq-specific: temperature and max_tokens from config
# ---------------------------------------------------------------------------


class TestGroqCallNonJson:
    @patch("agent_actions.llm.providers.groq.client.fire_event")
    @patch("agent_actions.llm.providers.groq.client.Groq")
    def test_temperature_and_max_tokens_from_config(self, mock_groq_cls, mock_fire):
        from agent_actions.llm.providers.groq.client import GroqClient

        config = {"model_name": "test-model", "temperature": 0.3, "max_tokens": 2000}

        mock_response = _make_openai_style_mocks("resp")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_groq_cls.return_value = mock_client

        GroqClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 2000

    @patch("agent_actions.llm.providers.groq.client.fire_event")
    @patch("agent_actions.llm.providers.groq.client.Groq")
    def test_none_temperature_and_max_tokens_use_defaults(self, mock_groq_cls, mock_fire):
        """When config has temperature=None / max_tokens=None, fall back to defaults."""
        from agent_actions.llm.providers.groq.client import GroqClient

        config = {"model_name": "test-model", "temperature": None, "max_tokens": None}

        mock_response = _make_openai_style_mocks("resp")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_groq_cls.return_value = mock_client

        GroqClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 1000


# ---------------------------------------------------------------------------
# Cohere call_json schema fix
# ---------------------------------------------------------------------------


class TestCohereCallJsonSchemaFix:
    """Cohere call_json correctly extracts field names from compiled schema."""

    @staticmethod
    def _mock_cohere_v2_response(text):
        content_block = MagicMock()
        content_block.text = text
        mock_response = MagicMock()
        mock_response.message.content = [content_block]
        mock_response.usage = None
        return mock_response

    @patch("agent_actions.llm.providers.cohere.client.fire_event")
    @patch("agent_actions.llm.providers.cohere.client.cohere")
    def test_compiled_schema_format(self, mock_cohere_mod, mock_fire):
        """schema={type: object, properties: {...}} extracts field names from properties."""
        from agent_actions.llm.providers.cohere.client import CohereClient

        compiled_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
        }
        config = {"model_name": "command-r"}

        mock_response = self._mock_cohere_v2_response('{"name": "Alice", "age": 30}')
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_cohere_mod.ClientV2.return_value = mock_client

        CohereClient.call_json("key", config, "prompt", "data", compiled_schema)

        call_args = mock_client.chat.call_args
        prompt_message = call_args[1]["messages"][0]["content"]
        assert "'name'" in prompt_message
        assert "'age'" in prompt_message
        assert "'type'" not in prompt_message
        assert "'properties'" not in prompt_message

    @patch("agent_actions.llm.providers.cohere.client.fire_event")
    @patch("agent_actions.llm.providers.cohere.client.cohere")
    def test_schema_none_handled_gracefully(self, mock_cohere_mod, mock_fire):
        """schema=None should not crash and prompt should not have empty fields."""
        from agent_actions.llm.providers.cohere.client import CohereClient

        config = {"model_name": "command-r"}

        mock_response = self._mock_cohere_v2_response('{"result": "ok"}')
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_cohere_mod.ClientV2.return_value = mock_client

        result = CohereClient.call_json("key", config, "prompt", "data", None)
        assert result is not None

        prompt_message = mock_client.chat.call_args[1]["messages"][0]["content"]
        assert "with the fields " not in prompt_message

    @patch("agent_actions.llm.providers.cohere.client.fire_event")
    @patch("agent_actions.llm.providers.cohere.client.cohere")
    def test_raw_schema_dict_still_works(self, mock_cohere_mod, mock_fire):
        """Raw dict schema (no 'properties' key) falls through to .keys()."""
        from agent_actions.llm.providers.cohere.client import CohereClient

        raw_schema = {"name": {"type": "string"}, "age": {"type": "integer"}}
        config = {"model_name": "command-r"}

        mock_response = self._mock_cohere_v2_response('{"name": "Bob", "age": 25}')
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_cohere_mod.ClientV2.return_value = mock_client

        result = CohereClient.call_json("key", config, "prompt", "data", raw_schema)
        assert result is not None


# ---------------------------------------------------------------------------
# Anthropic-specific tests
# ---------------------------------------------------------------------------


class TestAnthropicCallNonJson:
    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    def test_empty_response_raises_vendor_error(
        self, mock_anthropic_mod, mock_fire, base_agent_config
    ):
        from agent_actions.errors import VendorAPIError
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        tool_block = MagicMock(spec=[])
        del tool_block.text

        mock_response = MagicMock()
        mock_response.content = [tool_block]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 0
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_mod.Anthropic.return_value = mock_client

        with pytest.raises(VendorAPIError, match="Empty response"):
            AnthropicClient.call_non_json("key", base_agent_config, "prompt", "data")

    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    def test_no_tools_parameter_in_api_args(self, mock_anthropic_mod, mock_fire, base_agent_config):
        """Non-JSON mode must NOT include tools in the API call."""
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        mock_response = _make_anthropic_mocks("response")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_mod.Anthropic.return_value = mock_client

        AnthropicClient.call_non_json("key", base_agent_config, "prompt", "data")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert "tools" not in call_kwargs


class TestAnthropicCallJsonNormalization:
    """Anthropic call_json always returns List[Dict]."""

    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    def test_dict_response_wrapped_in_list(self, mock_anthropic_mod, mock_fire):
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        tool_block = MagicMock()
        tool_block.input = {"name": "Alice", "age": 30}

        mock_response = MagicMock()
        mock_response.content = [tool_block]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 20
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_mod.Anthropic.return_value = mock_client

        config = {"model_name": "claude-3-sonnet"}
        result = AnthropicClient.call_json("key", config, "prompt", "data", None)

        assert isinstance(result, list)
        assert result == [{"name": "Alice", "age": 30}]

    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    def test_list_response_returned_as_is(self, mock_anthropic_mod, mock_fire):
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        tool_block = MagicMock()
        tool_block.input = [{"name": "Alice"}, {"name": "Bob"}]

        mock_response = MagicMock()
        mock_response.content = [tool_block]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 20
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_mod.Anthropic.return_value = mock_client

        config = {"model_name": "claude-3-sonnet"}
        result = AnthropicClient.call_json("key", config, "prompt", "data", None)

        assert isinstance(result, list)
        assert result == [{"name": "Alice"}, {"name": "Bob"}]


class TestAnthropicSharedCallApi:
    """Anthropic _call_api is shared between call_json and call_non_json."""

    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    def test_max_tokens_from_config(self, mock_anthropic_mod, mock_fire):
        """max_tokens in API call should reflect actual config, not hardcoded 1024."""
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        config = {"model_name": "claude-3", "max_tokens": 4096}
        mock_response = _make_anthropic_mocks("response")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_mod.Anthropic.return_value = mock_client

        AnthropicClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == 4096

    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    def test_default_max_tokens_is_1024(self, mock_anthropic_mod, mock_fire):
        """When max_tokens is not in config, it should default to 1024."""
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        config = {"model_name": "claude-3"}
        mock_response = _make_anthropic_mocks("response")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_mod.Anthropic.return_value = mock_client

        AnthropicClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == 1024


# ---------------------------------------------------------------------------
# Ollama token counts
# ---------------------------------------------------------------------------


class TestOllamaTokenCounts:
    """Ollama extracts token counts from response attributes."""

    @patch("agent_actions.output.response.response_builder.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.maybe_inject_online_failure")
    @patch("agent_actions.llm.providers.ollama.client.OllamaClient._get_client")
    def test_call_json_extracts_token_counts(
        self, mock_get_client, mock_inject, mock_fire, mock_rb_fire
    ):
        from agent_actions.llm.providers.ollama.client import OllamaClient
        from agent_actions.logging.events import LLMResponseEvent

        mock_response = MagicMock()
        mock_response.message.content = '{"answer": "42"}'
        mock_response.prompt_eval_count = 50
        mock_response.eval_count = 25

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_get_client.return_value = mock_client

        config = {"model_name": "llama3"}
        OllamaClient.call_json(None, config, "prompt", "data")

        # LLMResponseEvent now fires from ResponseBuilder
        response_events = [
            call for call in mock_rb_fire.call_args_list if isinstance(call[0][0], LLMResponseEvent)
        ]
        assert len(response_events) >= 1
        event = response_events[0][0][0]
        assert event.prompt_tokens == 50
        assert event.completion_tokens == 25
        assert event.total_tokens == 75

    @patch("agent_actions.output.response.response_builder.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.maybe_inject_online_failure")
    @patch("agent_actions.llm.providers.ollama.client.OllamaClient._get_client")
    def test_call_non_json_extracts_token_counts(
        self, mock_get_client, mock_inject, mock_fire, mock_rb_fire
    ):
        from agent_actions.llm.providers.ollama.client import OllamaClient
        from agent_actions.logging.events import LLMResponseEvent

        mock_response = MagicMock()
        mock_response.message.content = "Hello world"
        mock_response.prompt_eval_count = 30
        mock_response.eval_count = 15

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_get_client.return_value = mock_client

        config = {"model_name": "llama3"}
        OllamaClient.call_non_json(None, config, "prompt", "data")

        # LLMResponseEvent now fires from ResponseBuilder
        response_events = [
            call for call in mock_rb_fire.call_args_list if isinstance(call[0][0], LLMResponseEvent)
        ]
        assert len(response_events) >= 1
        event = response_events[0][0][0]
        assert event.prompt_tokens == 30
        assert event.completion_tokens == 15
        assert event.total_tokens == 45

    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.maybe_inject_online_failure")
    @patch("agent_actions.llm.providers.ollama.client.OllamaClient._get_client")
    def test_missing_token_attrs_default_to_zero(self, mock_get_client, mock_inject, mock_fire):
        from agent_actions.llm.providers.ollama.client import OllamaClient

        mock_response = MagicMock(spec=["message"])
        mock_response.message.content = "response"

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_get_client.return_value = mock_client

        config = {"model_name": "llama3"}
        result = OllamaClient.call_non_json(None, config, "prompt", "data")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Schema compilation for new targets (groq + mistral parameterized)
# ---------------------------------------------------------------------------


class TestCompileUnifiedSchemaNewTargets:
    """compile_unified_schema supports groq, mistral, and cohere targets."""

    @pytest.mark.parametrize("target", ["groq", "mistral"], ids=["groq", "mistral"])
    def test_openai_compatible_format(self, target):
        result = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, target)

        assert result["name"] == "test_schema"
        assert "schema" in result
        assert result["schema"]["type"] == "object"
        assert "name" in result["schema"]["properties"]
        assert "age" in result["schema"]["properties"]
        assert result["schema"]["required"] == ["name"]

    def test_cohere_produces_native_format(self):
        result = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "cohere")

        assert result["type"] == "object"
        assert "name" in result["properties"]
        assert "age" in result["properties"]
        assert result["required"] == ["name"]
        assert "schema" not in result

    def test_unknown_target_raises_error(self):
        from agent_actions.errors import ConfigValidationError

        with pytest.raises(ConfigValidationError):
            compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "unknown_vendor")

    def test_valid_systems_list_includes_new_targets(self):
        """Error message for unknown target lists all valid systems including new ones."""
        from agent_actions.errors import ConfigValidationError

        with pytest.raises(ConfigValidationError) as exc_info:
            compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "invalid")

        valid_systems = exc_info.value.context["valid_systems"]
        assert "groq" in valid_systems
        assert "mistral" in valid_systems
        assert "cohere" in valid_systems


# ---------------------------------------------------------------------------
# Config fields include generation params
# ---------------------------------------------------------------------------


class TestConfigFieldsGenerationParams:
    """SIMPLE_CONFIG_FIELDS includes generation parameters."""

    def test_generation_params_present(self):
        from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS

        for field in ("temperature", "max_tokens", "top_p", "stop"):
            assert field in SIMPLE_CONFIG_FIELDS, f"{field} missing from SIMPLE_CONFIG_FIELDS"
            assert SIMPLE_CONFIG_FIELDS[field] is None, f"{field} should default to None"

    def test_inherit_simple_fields_inherits_generation_params(self):
        from agent_actions.output.response.config_fields import inherit_simple_fields

        agent = {}
        action = {"temperature": 0.5, "top_p": 0.9}
        defaults = {"max_tokens": 2000, "stop": ["\\n"]}

        inherit_simple_fields(agent, action, defaults)

        assert agent["temperature"] == 0.5
        assert agent["max_tokens"] == 2000
        assert agent["top_p"] == 0.9
        assert agent["stop"] == ["\\n"]


# ---------------------------------------------------------------------------
# Generation params helper (stop_as_list parameterized)
# ---------------------------------------------------------------------------


class TestExtractGenerationParams:
    """extract_generation_params helper centralises parameter extraction."""

    def test_extracts_core_params(self):
        from agent_actions.llm.providers.generation_params import extract_generation_params

        config = {"temperature": 0.5, "max_tokens": 100, "top_p": 0.9, "stop": "END"}
        result = extract_generation_params(config)
        assert result == {"temperature": 0.5, "max_tokens": 100, "top_p": 0.9, "stop": "END"}

    def test_skips_none_values(self):
        from agent_actions.llm.providers.generation_params import extract_generation_params

        config = {"temperature": None, "max_tokens": 100, "top_p": None, "stop": None}
        result = extract_generation_params(config)
        assert result == {"max_tokens": 100}

    def test_key_mapping(self):
        from agent_actions.llm.providers.generation_params import extract_generation_params

        config = {"max_tokens": 100, "stop": "END", "top_p": 0.9}
        result = extract_generation_params(
            config,
            key_map={"max_tokens": "max_output_tokens", "stop": "stop_sequences"},
        )
        assert result == {"max_output_tokens": 100, "stop_sequences": "END", "top_p": 0.9}

    @pytest.mark.parametrize(
        "stop_input,expected",
        [
            pytest.param("END", ["END"], id="string_wrapped"),
            pytest.param(["END", "STOP"], ["END", "STOP"], id="list_preserved"),
        ],
    )
    def test_stop_as_list(self, stop_input, expected):
        from agent_actions.llm.providers.generation_params import extract_generation_params

        result = extract_generation_params({"stop": stop_input}, stop_as_list=True)
        assert result == {"stop": expected}

    def test_extra_params(self):
        from agent_actions.llm.providers.generation_params import extract_generation_params

        config = {"temperature": 0.5, "frequency_penalty": 0.3, "presence_penalty": 0.1}
        result = extract_generation_params(
            config, extra_params=("frequency_penalty", "presence_penalty")
        )
        assert result == {
            "temperature": 0.5,
            "frequency_penalty": 0.3,
            "presence_penalty": 0.1,
        }

    def test_empty_config_returns_empty(self):
        from agent_actions.llm.providers.generation_params import extract_generation_params

        assert extract_generation_params({}) == {}

    def test_combined_key_map_and_stop_as_list(self):
        """Cohere-style: top_p→p, stop→stop_sequences (as list)."""
        from agent_actions.llm.providers.generation_params import extract_generation_params

        config = {"top_p": 0.9, "stop": "DONE"}
        result = extract_generation_params(
            config,
            key_map={"top_p": "p", "stop": "stop_sequences"},
            stop_as_list=True,
        )
        assert result == {"p": 0.9, "stop_sequences": ["DONE"]}


# ---------------------------------------------------------------------------
# top_p and stop forwarding
# ---------------------------------------------------------------------------


class TestOpenAITopPStopForwarding:
    """OpenAI forwards top_p, stop, frequency_penalty, presence_penalty."""

    @patch("agent_actions.llm.providers.openai.client.fire_event")
    @patch("agent_actions.llm.providers.openai.client.OpenAI")
    def test_call_json_forwards_all_params(self, mock_openai_cls, mock_fire):
        from agent_actions.llm.providers.openai.client import OpenAIClient

        config = {
            "model_name": "gpt-4",
            "temperature": 0.3,
            "max_tokens": 500,
            "top_p": 0.95,
            "stop": ["\\n"],
            "frequency_penalty": 0.5,
            "presence_penalty": 0.2,
        }

        mock_response = _make_openai_style_mocks('{"result": "ok"}')
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_cls.return_value = mock_client

        schema = {"name": "test", "strict": True, "schema": {"type": "object", "properties": {}}}
        OpenAIClient.call_json("key", config, "prompt", "data", schema)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 500
        assert call_kwargs["top_p"] == 0.95
        assert call_kwargs["stop"] == ["\\n"]
        assert call_kwargs["frequency_penalty"] == 0.5
        assert call_kwargs["presence_penalty"] == 0.2

    @patch("agent_actions.llm.providers.openai.client.fire_event")
    @patch("agent_actions.llm.providers.openai.client.OpenAI")
    def test_call_non_json_forwards_all_params(self, mock_openai_cls, mock_fire):
        from agent_actions.llm.providers.openai.client import OpenAIClient

        config = {
            "model_name": "gpt-4",
            "top_p": 0.8,
            "stop": "END",
            "frequency_penalty": 0.1,
            "presence_penalty": 0.3,
        }

        mock_response = _make_openai_style_mocks("response")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_cls.return_value = mock_client

        OpenAIClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["top_p"] == 0.8
        assert call_kwargs["stop"] == "END"
        assert call_kwargs["frequency_penalty"] == 0.1
        assert call_kwargs["presence_penalty"] == 0.3


class TestAnthropicStopForwarding:
    """Anthropic maps stop → stop_sequences (as list)."""

    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    def test_stop_string_wrapped_in_list(self, mock_anthropic_mod, mock_fire):
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        config = {"model_name": "claude-3", "stop": "END", "top_p": 0.9}
        mock_response = _make_anthropic_mocks("response")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_mod.Anthropic.return_value = mock_client

        AnthropicClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["stop_sequences"] == ["END"]
        assert call_kwargs["top_p"] == 0.9

    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    def test_stop_list_passed_directly(self, mock_anthropic_mod, mock_fire):
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        config = {"model_name": "claude-3", "stop": ["END", "STOP"]}
        mock_response = _make_anthropic_mocks("response")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_mod.Anthropic.return_value = mock_client

        AnthropicClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["stop_sequences"] == ["END", "STOP"]


class TestGeminiTopPStopForwarding:
    """Gemini maps stop → stop_sequences in GenerateContentConfig."""

    @patch("agent_actions.llm.providers.gemini.client.fire_event")
    @patch("agent_actions.llm.providers.gemini.client._build_client")
    def test_non_json_forwards_top_p_and_stop(self, mock_build_client, mock_fire):
        from agent_actions.llm.providers.gemini.client import GeminiClient

        config = {"model_name": "gemini-pro", "top_p": 0.85, "stop": "DONE"}

        mock_response = MagicMock()
        mock_response.text = "output"
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_build_client.return_value = mock_client

        GeminiClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.models.generate_content.call_args[1]
        gen_config = call_kwargs["config"]
        assert gen_config.top_p == 0.85
        assert gen_config.stop_sequences == ["DONE"]


class TestCohereTopPStopForwarding:
    """Cohere maps top_p → p and stop → stop_sequences."""

    @patch("agent_actions.llm.providers.cohere.client.fire_event")
    @patch("agent_actions.llm.providers.cohere.client.cohere")
    def test_call_json_maps_top_p_to_p(self, mock_cohere_mod, mock_fire):
        from agent_actions.llm.providers.cohere.client import CohereClient

        config = {"model_name": "command-r", "top_p": 0.9, "stop": ["\\n"]}

        mock_response = _make_cohere_mocks('{"result": "ok"}')
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_cohere_mod.ClientV2.return_value = mock_client

        CohereClient.call_json("key", config, "prompt", "data", None)

        call_kwargs = mock_client.chat.call_args[1]
        assert call_kwargs["p"] == 0.9
        assert call_kwargs["stop_sequences"] == ["\\n"]
        assert "top_p" not in call_kwargs

    @patch("agent_actions.llm.providers.cohere.client.fire_event")
    @patch("agent_actions.llm.providers.cohere.client.cohere")
    def test_call_non_json_maps_top_p_to_p(self, mock_cohere_mod, mock_fire):
        from agent_actions.llm.providers.cohere.client import CohereClient

        config = {"model_name": "command-r", "top_p": 0.7, "stop": "END"}

        mock_response = _make_cohere_mocks("response")
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_cohere_mod.ClientV2.return_value = mock_client

        CohereClient.call_non_json("key", config, "prompt", "data")

        call_kwargs = mock_client.chat.call_args[1]
        assert call_kwargs["p"] == 0.7
        assert call_kwargs["stop_sequences"] == ["END"]


class TestOllamaTopPStopForwarding:
    """Ollama maps top_p → options.top_p, stop → options.stop (as list)."""

    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.maybe_inject_online_failure")
    @patch("agent_actions.llm.providers.ollama.client.OllamaClient._get_client")
    def test_call_non_json_options_include_top_p_and_stop(
        self, mock_get_client, mock_inject, mock_fire
    ):
        from agent_actions.llm.providers.ollama.client import OllamaClient

        config = {"model_name": "llama3", "top_p": 0.9, "stop": "\\n"}

        mock_response = MagicMock()
        mock_response.message.content = "Hello"
        mock_response.prompt_eval_count = 10
        mock_response.eval_count = 5

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_get_client.return_value = mock_client

        OllamaClient.call_non_json(None, config, "prompt", "data")

        call_kwargs = mock_client.chat.call_args[1]
        options = call_kwargs["options"]
        assert options["top_p"] == 0.9
        assert options["stop"] == ["\\n"]


# ---------------------------------------------------------------------------
# SINGLE_RESPONSE_CLIENTS audit (collapsed to 1 test)
# ---------------------------------------------------------------------------


class TestSingleResponseClients:
    """All providers now return List[Dict] — SINGLE_RESPONSE_CLIENTS is empty."""

    def test_set_is_empty(self):
        from agent_actions.llm.realtime.services.invocation import SINGLE_RESPONSE_CLIENTS

        assert SINGLE_RESPONSE_CLIENTS == set()


# ---------------------------------------------------------------------------
# call_json normalization: dict → List[Dict] (parameterized across providers)
# ---------------------------------------------------------------------------


class TestCallJsonDictWrapping:
    """Cohere, Mistral, and Gemini call_json wrap single-dict response in a list."""

    @patch("agent_actions.llm.providers.cohere.client.fire_event")
    @patch("agent_actions.llm.providers.cohere.client.cohere")
    def test_cohere_dict_wrapped_in_list(self, mock_cohere_mod, mock_fire):
        from agent_actions.llm.providers.cohere.client import CohereClient

        mock_response = _make_cohere_mocks('{"name": "Alice"}')
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_cohere_mod.ClientV2.return_value = mock_client

        result = CohereClient.call_json("key", {"model_name": "command-r"}, "prompt", "data", None)
        assert isinstance(result, list)
        assert result == [{"name": "Alice"}]

    @patch("agent_actions.llm.providers.mistral.client.fire_event")
    @patch("agent_actions.llm.providers.mistral.client.Mistral")
    def test_mistral_dict_wrapped_in_list(self, mock_mistral_cls, mock_fire):
        from agent_actions.llm.providers.mistral.client import MistralClient

        mock_response = _make_mistral_mocks('{"name": "Alice"}')
        mock_client = MagicMock()
        mock_client.chat.complete.return_value = mock_response
        mock_mistral_cls.return_value = mock_client

        result = MistralClient.call_json(
            "key", {"model_name": "mistral-large"}, "prompt", "data", None
        )
        assert isinstance(result, list)
        assert result == [{"name": "Alice"}]

    @patch("agent_actions.llm.providers.gemini.client.fire_event")
    @patch("agent_actions.llm.providers.gemini.client._build_client")
    def test_gemini_dict_wrapped_in_list(self, mock_build_client, mock_fire):
        from agent_actions.llm.providers.gemini.client import GeminiClient

        mock_response = MagicMock()
        mock_response.text = '{"name": "Alice"}'
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_build_client.return_value = mock_client

        result = GeminiClient.call_json("key", {"model_name": "gemini-pro"}, "prompt", "data", None)
        assert isinstance(result, list)
        assert result == [{"name": "Alice"}]


# ---------------------------------------------------------------------------
# Ollama set_last_usage
# ---------------------------------------------------------------------------


class TestOllamaSetLastUsage:
    """Ollama calls set_last_usage() when token counts are available."""

    @patch("agent_actions.output.response.response_builder.set_last_usage")
    @patch("agent_actions.output.response.response_builder.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.maybe_inject_online_failure")
    @patch("agent_actions.llm.providers.ollama.client.OllamaClient._get_client")
    def test_call_json_calls_set_last_usage(
        self, mock_get_client, mock_inject, mock_fire, _mock_rb_fire, mock_set_usage
    ):
        from agent_actions.llm.providers.ollama.client import OllamaClient

        mock_response = MagicMock()
        mock_response.message.content = '{"answer": "42"}'
        mock_response.prompt_eval_count = 50
        mock_response.eval_count = 25

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_get_client.return_value = mock_client

        OllamaClient.call_json(None, {"model_name": "llama3"}, "prompt", "data")

        mock_set_usage.assert_called_once_with(
            {"input_tokens": 50, "output_tokens": 25, "total_tokens": 75}
        )

    @patch("agent_actions.output.response.response_builder.set_last_usage")
    @patch("agent_actions.output.response.response_builder.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.maybe_inject_online_failure")
    @patch("agent_actions.llm.providers.ollama.client.OllamaClient._get_client")
    def test_call_non_json_calls_set_last_usage(
        self, mock_get_client, mock_inject, mock_fire, _mock_rb_fire, mock_set_usage
    ):
        from agent_actions.llm.providers.ollama.client import OllamaClient

        mock_response = MagicMock()
        mock_response.message.content = "Hello"
        mock_response.prompt_eval_count = 30
        mock_response.eval_count = 15

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_get_client.return_value = mock_client

        OllamaClient.call_non_json(None, {"model_name": "llama3"}, "prompt", "data")

        mock_set_usage.assert_called_once_with(
            {"input_tokens": 30, "output_tokens": 15, "total_tokens": 45}
        )

    @patch("agent_actions.output.response.response_builder.set_last_usage")
    @patch("agent_actions.output.response.response_builder.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client.maybe_inject_online_failure")
    @patch("agent_actions.llm.providers.ollama.client.OllamaClient._get_client")
    def test_zero_tokens_skips_set_last_usage(
        self, mock_get_client, mock_inject, mock_fire, _mock_rb_fire, mock_set_usage
    ):
        from agent_actions.llm.providers.ollama.client import OllamaClient

        mock_response = MagicMock(spec=["message"])
        mock_response.message.content = "response"

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_get_client.return_value = mock_client

        OllamaClient.call_non_json(None, {"model_name": "llama3"}, "prompt", "data")

        mock_set_usage.assert_not_called()


# ---------------------------------------------------------------------------
# Gemini call_json normalization (no system_instruction in JSON mode)
# ---------------------------------------------------------------------------


class TestGeminiCallJsonNormalization:
    @patch("agent_actions.llm.providers.gemini.client.fire_event")
    @patch("agent_actions.llm.providers.gemini.client._build_client")
    def test_json_mode_uses_response_mime_type(self, mock_build_client, mock_fire):
        """call_json should set response_mime_type in GenerateContentConfig."""
        from agent_actions.llm.providers.gemini.client import GeminiClient

        mock_response = MagicMock()
        mock_response.text = '{"name": "Alice"}'
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_build_client.return_value = mock_client

        GeminiClient.call_json("key", {"model_name": "gemini-pro"}, "prompt", "data", None)

        call_kwargs = mock_client.models.generate_content.call_args[1]
        config = call_kwargs["config"]
        assert config.response_mime_type == "application/json"


# ---------------------------------------------------------------------------
# Cohere call_non_json content guard
# ---------------------------------------------------------------------------


class TestCohereCallNonJsonContentGuard:
    """Cohere call_non_json raises VendorAPIError on empty content."""

    @patch("agent_actions.llm.providers.cohere.client.fire_event")
    @patch("agent_actions.llm.providers.cohere.client.cohere")
    def test_empty_content_raises_vendor_error(self, mock_cohere_mod, mock_fire):
        from agent_actions.errors import VendorAPIError
        from agent_actions.llm.providers.cohere.client import CohereClient

        mock_response = MagicMock()
        mock_response.message.content = []
        mock_response.usage = None

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_cohere_mod.ClientV2.return_value = mock_client

        with pytest.raises(VendorAPIError):
            CohereClient.call_non_json("key", {"model_name": "command-r"}, "prompt", "data")

    @patch("agent_actions.llm.providers.cohere.client.fire_event")
    @patch("agent_actions.llm.providers.cohere.client.cohere")
    def test_none_message_raises_vendor_error(self, mock_cohere_mod, mock_fire):
        from agent_actions.errors import VendorAPIError
        from agent_actions.llm.providers.cohere.client import CohereClient

        mock_response = MagicMock()
        mock_response.message = None
        mock_response.usage = None

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        mock_cohere_mod.ClientV2.return_value = mock_client

        with pytest.raises(VendorAPIError):
            CohereClient.call_non_json("key", {"model_name": "command-r"}, "prompt", "data")


# ---------------------------------------------------------------------------
# BaseClient contract (parameterized)
# ---------------------------------------------------------------------------


class TestBaseClientReturnTypes:
    """BaseClient abstract methods declare List[Dict] return types."""

    @pytest.mark.parametrize(
        "method_name",
        [
            pytest.param("call_json", id="call_json"),
            pytest.param("call_non_json", id="call_non_json"),
        ],
    )
    def test_return_annotation_is_list(self, method_name):
        from agent_actions.llm.providers.client_base import BaseClient

        hints = typing.get_type_hints(getattr(BaseClient, method_name))
        origin = getattr(hints["return"], "__origin__", None)
        assert origin is list
