# Batch Provider Architecture Changes

## Overview
This document describes the refactoring of batch processing to support multiple providers beyond OpenAI.

## What Was Done

### 1. Created Provider Abstraction Layer
- **Base Provider Interface** (`base.py`):
  - `BatchProvider` abstract base class defining the contract for all providers
  - `BatchTask` dataclass for provider-agnostic task representation
  - `BatchResult` dataclass for standardized result format
  - Clear transformation methods: `format_task_for_provider()` and `parse_provider_response()`

### 2. Implemented OpenAI Provider
- **OpenAI Implementation** (`openai_provider.py`):
  - Extracted all OpenAI-specific code from BatchService
  - Handles format transformations:
    - Input: `BatchTask` → OpenAI's specific JSON format
    - Output: OpenAI's nested response → flat `BatchResult`
  - Maintains all existing functionality (retries, error handling, etc.)

### 3. Updated BatchService
- **Refactored BatchService** to use provider interface:
  - Constructor now accepts any `BatchProvider` implementation
  - All OpenAI-specific code removed
  - Works with standardized `BatchTask` and `BatchResult` objects
  - Provider handles all format-specific transformations

## Architecture Benefits

### Separation of Concerns
- **Tool Logic**: Workflow management, registry, context tracking, lineage
- **Provider Logic**: API integration, format transformation, schema compilation

### Data Flow
```
Agent Data → BatchTask → Provider Format → Provider API → Provider Response → BatchResult → Workflow Format
```

### Key Design Principle
Different providers have different input/output formats, but we intercept and transform these to match our standardized format. This ensures the rest of the agent-actions system doesn't need to know about provider-specific details.

## What Comes Next

### 1. Additional Providers
Create new providers by implementing the `BatchProvider` interface:
- **Anthropic Claude Batch API** (when available)
- **Google Vertex AI Batch Prediction**
- **AWS Bedrock Batch Inference**
- **Custom Internal APIs**

Example structure:
```python
class AnthropicBatchProvider(BatchProvider):
    def format_task_for_provider(self, batch_task, schema):
        # Transform to Anthropic's format
        
    def parse_provider_response(self, raw_response):
        # Transform from Anthropic's format to BatchResult
```

### 2. Provider Factory Pattern
Create a factory to instantiate providers based on configuration:
```python
class BatchProviderFactory:
    @staticmethod
    def create_provider(provider_type: str, config: dict) -> BatchProvider:
        if provider_type == "openai":
            return OpenAIBatchProvider(api_key=config.get("api_key"))
        elif provider_type == "anthropic":
            return AnthropicBatchProvider(api_key=config.get("api_key"))
        # ... more providers
```

### 3. Support for 3 Parallel Batch Agents
Update the workflow system to:
- Track multiple batch agents in the registry
- Support different providers per agent
- Handle dependencies between batch agents
- Aggregate status across all batch agents

Configuration example:
```yaml
batch_agent_1:
  - agent_type: enrichment
    run_mode: batch
    batch_provider: openai
    model_name: "gpt-4o-mini"
    
batch_agent_2:
  - agent_type: classification
    run_mode: batch
    batch_provider: anthropic  # Different provider
    model_name: "claude-3-haiku"
    
batch_agent_3:
  - agent_type: summarization
    run_mode: batch
    batch_provider: openai
    model_name: "gpt-3.5-turbo"
```

### 4. Provider Capabilities
Add capability checking to providers:
- Schema validation support
- Streaming support
- Maximum batch size
- Supported file formats
- Cost per request

### 5. Provider-Specific Features
Allow providers to expose unique features:
- OpenAI: JSON mode, function calling
- Anthropic: Constitutional AI, XML parsing
- Custom: Domain-specific capabilities

### 6. Testing Framework
Create provider testing utilities:
- Mock provider for testing
- Provider compliance tests
- Format transformation validation
- End-to-end integration tests

## Migration Guide

### For Existing Workflows
No changes needed - BatchService defaults to OpenAI provider for backward compatibility.

### For New Providers
1. Implement the `BatchProvider` interface
2. Add provider to the factory
3. Update agent configuration with `batch_provider: your_provider`
4. Test with existing workflows

## Future Considerations

### Performance Optimizations
- Provider-specific connection pooling
- Batch size optimization per provider
- Parallel submission to multiple providers

### Monitoring and Observability
- Provider-specific metrics
- Cost tracking per provider
- Performance comparisons

### Error Handling
- Provider-specific retry strategies
- Fallback providers
- Circuit breaker patterns