"""
Vendor configuration models for LLM providers.

This module provides vendor configuration classes and enums used across the agent-actions framework
by both batch and realtime modes, as well as response processing.

Moved from llm_invocation/realtime/ to utilities/ to reflect its shared usage.
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List, Literal, Union
from enum import Enum

class VendorType(str, Enum):
    """Supported LLM vendor types."""
    OPENAI = 'openai'
    ANTHROPIC = 'anthropic'
    GOOGLE = 'google'
    GEMINI = 'gemini'
    GROQ = 'groq'
    COHERE = 'cohere'
    MISTRAL = 'mistral'
    DEEPSEEK = 'deepseek'
    OLLAMA = 'ollama'
    TOOL = 'tool'

class ResponseFormat(str, Enum):
    """Response format types."""
    JSON = 'json'
    TEXT = 'text'
    JSON_SCHEMA = 'json_schema'

class BaseVendorConfig(BaseModel):
    """Base configuration for all LLM vendors."""
    vendor_type: VendorType = Field(..., description='Type of LLM vendor')
    api_key_env_name: str = Field(..., description='Environment variable name for API key')
    model_name: str = Field(..., description='Model name to use')
    default_timeout: int = Field(default=60, ge=1, description='Default request timeout in seconds')
    max_retries: int = Field(default=3, ge=0, description='Maximum retry attempts')
    json_mode: bool = Field(default=True, description='Enable JSON mode by default')
    max_tokens: Optional[int] = Field(default=None, ge=1, description='Maximum tokens in response')
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description='Sampling temperature')
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0, description='Top-p sampling parameter')
    model_config = {'extra': 'allow'}

class OpenAIConfig(BaseVendorConfig):
    """Configuration specific to OpenAI."""
    vendor_type: Literal[VendorType.OPENAI] = VendorType.OPENAI
    api_key_env_name: str = 'OPENAI_API_KEY'
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    top_k: Optional[int] = Field(default=None, ge=1)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON_SCHEMA)

class AnthropicConfig(BaseVendorConfig):
    """Configuration specific to Anthropic Claude."""
    vendor_type: Literal[VendorType.ANTHROPIC] = VendorType.ANTHROPIC
    api_key_env_name: str = 'CLAUDE_API_KEY'
    anthropic_version: str = Field(default='2023-06-01', description='API version header')
    enable_prompt_caching: bool = Field(default=False, description='Enable prompt caching')
    tools_mode: bool = Field(default=True, description='Use tools for JSON responses')

class GoogleConfig(BaseVendorConfig):
    """Configuration specific to Google Gemini."""
    vendor_type: Literal[VendorType.GOOGLE] = VendorType.GOOGLE
    api_key_env_name: str = 'GOOGLE_API_KEY'
    safety_settings: Optional[Dict[str, Any]] = Field(default=None)
    generation_config: Optional[Dict[str, Any]] = Field(default=None)

class GroqConfig(BaseVendorConfig):
    """Configuration specific to Groq."""
    vendor_type: Literal[VendorType.GROQ] = VendorType.GROQ
    api_key_env_name: str = 'GROQ_API_KEY'

class CohereConfig(BaseVendorConfig):
    """Configuration specific to Cohere."""
    vendor_type: Literal[VendorType.COHERE] = VendorType.COHERE
    api_key_env_name: str = 'COHERE_API_KEY'
    k: Optional[int] = Field(default=None, ge=1, description='Top-k sampling')
    p: Optional[float] = Field(default=None, ge=0.0, le=1.0, description='Top-p sampling')

class MistralConfig(BaseVendorConfig):
    """Configuration specific to Mistral."""
    vendor_type: Literal[VendorType.MISTRAL] = VendorType.MISTRAL
    api_key_env_name: str = 'MISTRAL_API_KEY'

class DeepSeekConfig(BaseVendorConfig):
    """Configuration specific to DeepSeek."""
    vendor_type: Literal[VendorType.DEEPSEEK] = VendorType.DEEPSEEK
    api_key_env_name: str = 'DEEPSEEK_API_KEY'

class OllamaConfig(BaseVendorConfig):
    """Configuration specific to Ollama (local models)."""
    vendor_type: Literal[VendorType.OLLAMA] = VendorType.OLLAMA
    api_key_env_name: str = 'OLLAMA_API_KEY'
    base_url: str = Field(default='http://localhost:11434', description='Ollama server URL')

class ToolVendorConfig(BaseVendorConfig):
    """Configuration for tool-based vendors (non-LLM)."""
    vendor_type: Literal[VendorType.TOOL] = VendorType.TOOL
    api_key_env_name: str = 'TOOL_API_KEY'
    json_mode: bool = False
VendorConfig = Union[OpenAIConfig, AnthropicConfig, GoogleConfig, GroqConfig, CohereConfig, MistralConfig, DeepSeekConfig, OllamaConfig, ToolVendorConfig]

class VendorRegistry(BaseModel):
    """Registry for all configured vendors."""
    vendors: Dict[str, VendorConfig] = Field(default_factory=dict, description='Map of vendor name to vendor configuration')
    default_vendor: Optional[str] = Field(default=None, description='Default vendor to use when not specified (must be explicitly configured)')

    def get_vendor_config(self, vendor_name: str) -> Optional[VendorConfig]:
        """Get configuration for a specific vendor."""
        return self.vendors.get(vendor_name)

    def get_default_vendor_config(self) -> Optional[VendorConfig]:
        """Get the default vendor configuration."""
        return self.vendors.get(self.default_vendor)

    def register_vendor(self, name: str, config: VendorConfig):
        """Register a new vendor configuration."""
        self.vendors[name] = config

    def list_vendor_types(self) -> List[VendorType]:
        """Get list of all registered vendor types."""
        return [config.vendor_type for config in self.vendors.values()]

    @classmethod
    def create_default_registry(cls) -> 'VendorRegistry':
        """Create a registry with default vendor configurations."""
        registry = cls()
        registry.register_vendor('openai', OpenAIConfig(model_name='gpt-4o-mini'))
        registry.register_vendor('claude', AnthropicConfig(model_name='claude-3-sonnet-20240229'))
        registry.register_vendor('gemini', GoogleConfig(model_name='gemini-1.5-flash'))
        return registry
__all__ = ['VendorType', 'ResponseFormat', 'BaseVendorConfig', 'OpenAIConfig', 'AnthropicConfig', 'GoogleConfig', 'GroqConfig', 'CohereConfig', 'MistralConfig', 'DeepSeekConfig', 'OllamaConfig', 'ToolVendorConfig', 'VendorConfig', 'VendorRegistry']