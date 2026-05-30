"""Tests that vendor configs reject unknown keys (extra='forbid').

Validates that typos in vendor configuration YAML (e.g., 'temperture'
instead of 'temperature') raise ValidationError instead of being
silently accepted.
"""

import pytest
from pydantic import ValidationError

from agent_actions.llm.config.vendor import (
    AgacProviderConfig,
    AnthropicConfig,
    CohereConfig,
    GeminiConfig,
    GroqConfig,
    HitlVendorConfig,
    OllamaCloudConfig,
    OllamaLocalConfig,
    OpenAIConfig,
    ToolVendorConfig,
)


@pytest.mark.parametrize(
    "cls",
    [
        OpenAIConfig,
        AnthropicConfig,
        GeminiConfig,
        GroqConfig,
        CohereConfig,
        OllamaLocalConfig,
        OllamaCloudConfig,
        ToolVendorConfig,
        HitlVendorConfig,
        AgacProviderConfig,
    ],
)
class TestVendorConfigForbidsExtraFields:
    """All vendor config subclasses reject unknown keys."""

    def test_rejects_unknown_field(self, cls):
        with pytest.raises(ValidationError, match="bogus_field"):
            cls(model_name="test", bogus_field="value")

    def test_rejects_typo_field(self, cls):
        with pytest.raises(ValidationError, match="temperture"):
            cls(model_name="test", temperture=0.7)


class TestVendorConfigAcceptsValidFields:
    """Smoke tests that declared fields still work."""

    def test_openai_frequency_penalty(self):
        config = OpenAIConfig(model_name="gpt-4o", frequency_penalty=0.5)
        assert config.frequency_penalty == 0.5

    def test_anthropic_version(self):
        config = AnthropicConfig(model_name="claude-3", anthropic_version="2024-01-01")
        assert config.anthropic_version == "2024-01-01"

    def test_base_temperature(self):
        config = OpenAIConfig(model_name="gpt-4o", temperature=0.7)
        assert config.temperature == 0.7
