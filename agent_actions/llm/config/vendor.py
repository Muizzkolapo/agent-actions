"""
Vendor configuration models for LLM providers.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_actions.config.defaults import OllamaDefaults


class VendorType(str, Enum):
    """Supported LLM vendor types."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    # GOOGLE is an alias for GEMINI so users can write vendor_type="google"
    # and resolve to the same Gemini provider. Both names share the "gemini" value.
    GOOGLE = "gemini"
    GROQ = "groq"
    COHERE = "cohere"
    MISTRAL = "mistral"
    OLLAMA = "ollama"
    TOOL = "tool"
    HITL = "hitl"
    AGAC_PROVIDER = "agac-provider"


class ResponseFormat(str, Enum):
    """Response format types."""

    JSON = "json"
    TEXT = "text"
    JSON_SCHEMA = "json_schema"


class BaseVendorConfig(BaseModel):
    """Base configuration for all LLM vendors."""

    vendor_type: VendorType = Field(..., description="Type of LLM vendor")
    api_key_env_name: str = Field(..., description="Environment variable name for API key")
    model_name: str = Field(..., description="Model name to use")
    default_timeout: int = Field(default=60, ge=1, description="Default request timeout in seconds")
    json_mode: bool = Field(default=True, description="Enable JSON mode by default")
    max_tokens: int | None = Field(default=None, ge=1, description="Maximum tokens in response")
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Sampling temperature"
    )
    top_p: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Top-p sampling parameter"
    )
    model_config = {"extra": "allow"}


class OpenAIConfig(BaseVendorConfig):
    """Configuration specific to OpenAI."""

    vendor_type: Literal[VendorType.OPENAI] = VendorType.OPENAI
    api_key_env_name: str = "OPENAI_API_KEY"
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    top_k: int | None = Field(default=None, ge=1)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON_SCHEMA)


class AnthropicConfig(BaseVendorConfig):
    """Configuration specific to Anthropic Claude."""

    vendor_type: Literal[VendorType.ANTHROPIC] = VendorType.ANTHROPIC
    api_key_env_name: str = "ANTHROPIC_API_KEY"
    anthropic_version: str = Field(default="2023-06-01", description="API version header")
    enable_prompt_caching: bool = Field(default=False, description="Enable prompt caching")
    tools_mode: bool = Field(default=True, description="Use tools for JSON responses")


class GeminiConfig(BaseVendorConfig):
    """Configuration specific to Google Gemini."""

    vendor_type: Literal[VendorType.GEMINI] = VendorType.GEMINI
    api_key_env_name: str = "GEMINI_API_KEY"
    safety_settings: dict[str, Any] | None = Field(default=None)
    generation_config: dict[str, Any] | None = Field(default=None)


GoogleConfig = GeminiConfig


class GroqConfig(BaseVendorConfig):
    """Configuration specific to Groq."""

    vendor_type: Literal[VendorType.GROQ] = VendorType.GROQ
    api_key_env_name: str = "GROQ_API_KEY"


class CohereConfig(BaseVendorConfig):
    """Configuration specific to Cohere."""

    vendor_type: Literal[VendorType.COHERE] = VendorType.COHERE
    api_key_env_name: str = "COHERE_API_KEY"
    k: int | None = Field(default=None, ge=1, description="Top-k sampling")
    p: float | None = Field(default=None, ge=0.0, le=1.0, description="Top-p sampling")


class MistralConfig(BaseVendorConfig):
    """Configuration specific to Mistral."""

    vendor_type: Literal[VendorType.MISTRAL] = VendorType.MISTRAL
    api_key_env_name: str = "MISTRAL_API_KEY"


class OllamaConfig(BaseVendorConfig):
    """Configuration specific to Ollama (local models)."""

    vendor_type: Literal[VendorType.OLLAMA] = VendorType.OLLAMA
    api_key_env_name: str = "OLLAMA_API_KEY"
    base_url: str = Field(default=OllamaDefaults.BASE_URL, description="Ollama server URL")


class ToolVendorConfig(BaseVendorConfig):
    """Configuration for tool-based vendors (non-LLM).

    Tool actions run local Python functions, so api_key_env_name is a
    no-op placeholder required by the base class.
    """

    vendor_type: Literal[VendorType.TOOL] = VendorType.TOOL
    api_key_env_name: str = "TOOL_NO_KEY_REQUIRED"
    model_name: str = "tool"
    json_mode: bool = False


class HitlVendorConfig(BaseVendorConfig):
    """Configuration for HITL workflow vendor (non-LLM).

    HITL actions do not call external APIs, so api_key_env_name is a
    no-op placeholder required by the base class.
    """

    vendor_type: Literal[VendorType.HITL] = VendorType.HITL
    api_key_env_name: str = "HITL_NO_KEY_REQUIRED"
    model_name: str = "hitl"
    json_mode: bool = True


class AgacProviderConfig(BaseVendorConfig):
    """Configuration for Agac mock provider (testing/development)."""

    vendor_type: Literal[VendorType.AGAC_PROVIDER] = VendorType.AGAC_PROVIDER
    api_key_env_name: str = "AGAC_API_KEY"
    json_mode: bool = True


VendorConfig = (
    OpenAIConfig
    | AnthropicConfig
    | GoogleConfig
    | GroqConfig
    | CohereConfig
    | MistralConfig
    | OllamaConfig
    | ToolVendorConfig
    | HitlVendorConfig
    | AgacProviderConfig
)


class VendorRegistry(BaseModel):
    """Registry for all configured vendors."""

    vendors: dict[str, VendorConfig] = Field(
        default_factory=dict, description="Map of vendor name to vendor configuration"
    )
    default_vendor: str | None = Field(
        default=None,
        description="Default vendor to use when not specified (must be explicitly configured)",
    )

    def get_vendor_config(self, vendor_name: str) -> VendorConfig | None:
        """Get configuration for a specific vendor."""
        return self.vendors.get(vendor_name)

    def get_default_vendor_config(self) -> VendorConfig | None:
        """Get the default vendor configuration."""
        return self.vendors.get(self.default_vendor)  # type: ignore[arg-type]

    def register_vendor(self, name: str, config: VendorConfig):
        """Register a new vendor configuration."""
        self.vendors[name] = config

    def list_vendor_types(self) -> list[VendorType]:
        """Get list of all registered vendor types."""
        return [config.vendor_type for config in self.vendors.values()]

    @classmethod
    def create_default_registry(cls) -> "VendorRegistry":
        """Create a registry with default vendor configurations."""
        registry = cls()
        registry.register_vendor("openai", OpenAIConfig(model_name="gpt-4o-mini"))
        registry.register_vendor("claude", AnthropicConfig(model_name="claude-3-sonnet-20240229"))
        registry.register_vendor("gemini", GoogleConfig(model_name="gemini-1.5-flash"))
        return registry


__all__ = [
    "VendorType",
    "ResponseFormat",
    "BaseVendorConfig",
    "OpenAIConfig",
    "AnthropicConfig",
    "GeminiConfig",
    "GoogleConfig",
    "GroqConfig",
    "CohereConfig",
    "MistralConfig",
    "OllamaConfig",
    "ToolVendorConfig",
    "HitlVendorConfig",
    "AgacProviderConfig",
    "VendorConfig",
    "VendorRegistry",
]
