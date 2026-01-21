# Config Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `vendor_config.py` | Module | Vendor configuration models for LLM providers. | - |
| `VendorType` | Class | Supported LLM vendor types. | - |
| `ResponseFormat` | Class | Response format types. | - |
| `BaseVendorConfig` | Class | Base configuration for all LLM vendors. | - |
| `OpenAIConfig` | Class | Configuration specific to OpenAI. | - |
| `AnthropicConfig` | Class | Configuration specific to Anthropic Claude. | - |
| `GoogleConfig` | Class | Configuration specific to Google Gemini. | - |
| `GroqConfig` | Class | Configuration specific to Groq. | - |
| `CohereConfig` | Class | Configuration specific to Cohere. | - |
| `MistralConfig` | Class | Configuration specific to Mistral. | - |
| `OllamaConfig` | Class | Configuration specific to Ollama (local models). | - |
| `ToolVendorConfig` | Class | Configuration for tool-based vendors (non-LLM). | - |
| `VendorRegistry` | Class | Registry for all configured vendors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_vendor_config` | Method | Get configuration for a specific vendor. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_default_vendor_config` | Method | Get the default vendor configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_vendor` | Method | Register a new vendor configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `list_vendor_types` | Method | Get list of all registered vendor types. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_default_registry` | Method | Create a registry with default vendor configurations. | - |
