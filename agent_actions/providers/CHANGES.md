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

## What Was Done (Phase 2)

### 1. Implemented Gemini Batch Provider
- **Gemini Implementation** (`gemini_provider.py`):
  - Full implementation of `BatchProvider` interface for Google's Gemini API
  - Handles format transformations:
    - Input: `BatchTask` → Gemini's specific JSON format with "key" and "request"
    - Output: Gemini's nested response → flat `BatchResult`
  - Supports all Gemini models (Flash, Pro variants)
  - Integrates with Google's Files API for batch uploads

### 2. Created Provider Factory
- **Factory Pattern** (`factory.py`):
  - Simple factory to instantiate providers based on configuration
  - Supports environment variable API keys
  - Easy to extend with new providers

### 3. Updated BatchService for Dynamic Provider Selection
- **Multi-Provider Support**:
  - BatchService now selects providers based on agent configuration
  - Added `batch_provider` field to agent configuration types
  - Provider type stored in batch registry for proper status checking
  - Backward compatible - defaults to OpenAI if not specified

### 4. Enhanced BatchService Integration
- **Dynamic Provider Resolution**:
  - BatchService caches providers by type to avoid recreating them
  - Provider type stored in batch registry for proper tracking across operations
  - All batch operations (submit, check_status, retrieve_results) now use appropriate provider
  - Added `_get_provider_for_batch_id()` method to retrieve correct provider for existing jobs

### 5. Configuration System Updates
- **Added `batch_provider` field** to `AgentEntryDict` configuration type
- **Updated project dependencies** to include `google-genai` package
- **Environment variable support** for API keys (GOOGLE_API_KEY, OPENAI_API_KEY)

### 6. Error Handling and Robustness
- **Graceful dependency handling**: System doesn't crash if `google-genai` is not installed
- **Clear error messages**: Users get helpful installation instructions when dependencies are missing
- **Provider validation**: Validates model compatibility before creating batch jobs
- **Backward compatibility**: Existing OpenAI workflows continue to work unchanged

### 7. Documentation and Troubleshooting
- Created comprehensive Gemini provider documentation (`GEMINI_BATCH.md`)
- Includes installation instructions and troubleshooting guide
- Migration guide from OpenAI to Gemini
- Examples of multi-provider workflows

## What Comes Next

### 1. Additional Providers
Create new providers by implementing the `BatchProvider` interface:
- **Anthropic Claude Batch API** (when available)
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

### 2. Enhanced Multi-Provider Workflows
Now that the provider factory is implemented, focus on advanced multi-provider features:
- **Provider-specific optimizations**: Different batch sizes, retry strategies per provider
- **Cost optimization**: Automatic provider selection based on cost and performance
- **Fallback mechanisms**: Automatic failover between providers

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

## Implementation Summary

### Current Status (Phase 2 Complete)
The batch processing system now supports multiple providers through a clean abstraction layer:

- ✅ **Gemini Batch Provider**: Fully implemented and tested
- ✅ **Provider Factory**: Dynamic provider instantiation
- ✅ **BatchService Integration**: Multi-provider support with proper tracking
- ✅ **Configuration System**: `batch_provider` field support
- ✅ **Error Handling**: Graceful dependency management
- ✅ **Documentation**: Complete usage and migration guides

### Usage
Users can now specify different providers per agent:

```yaml
workflow: multi_provider_example
agents:
  - agent_type: classifier
    model_name: gpt-4o-mini
    batch_provider: openai
    run_mode: batch
    
  - agent_type: enrichment  
    model_name: gemini-2.5-flash
    batch_provider: gemini
    run_mode: batch
    dependencies: [classifier]
```

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