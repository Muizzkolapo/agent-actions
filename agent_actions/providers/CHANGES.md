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
- **Consolidated provider configuration** - now uses `model_vendor` field for both regular and batch processing
- **Deprecated `batch_provider` field** - maintained for backward compatibility with deprecation warnings
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

## What Was Done (Phase 3)

### 1. Implemented Anthropic Batch Provider
- **Anthropic Implementation** (`anthropic_provider.py`):
  - Full implementation of `BatchProvider` interface for Anthropic's Message Batches API
  - Handles format transformations:
    - Input: `BatchTask` → Anthropic's Message Batches format with "custom_id" and "params"
    - Output: Anthropic's batch response → flat `BatchResult`
  - Supports all Claude models available for batch processing
  - **Direct HTTP Submission**: No file upload required
  - **Streaming Results**: Real-time result retrieval
  - **Prompt Caching**: Optional cost optimization feature

### 2. Fixed Critical Implementation Issues
- **System Message Format Fix**:
  - Fixed incorrect system message placement in messages array
  - Anthropic requires system messages as top-level `system` parameter
  - Resolved `invalid_request_error` that was causing all batches to fail
  
- **Mock Implementation Removal**:
  - Replaced all mock/placeholder code with real Anthropic API calls
  - Updated `submit_batch()`, `check_status()`, and `retrieve_results()` methods
  - Fixed the "Mock retrieval of Anthropic batch results" error

### 3. Implemented JSON Mode for Structured Output
- **Tool-Based JSON Mode**:
  ```python
  # Anthropic doesn't have OpenAI-style JSON mode
  # Instead uses tool use to force structured output
  tools = [{
      "name": "json_response",
      "description": "Provide structured JSON output",
      "input_schema": {your_schema}
  }]
  ```
  
- **Schema Integration**:
  - Added `_create_json_tool_from_schema()` method
  - Converts JSON schemas to Anthropic tool definitions
  - Forces Claude to respond with structured JSON via tool use
  
- **Enhanced Response Parsing**:
  - Updated `parse_provider_response()` to handle tool use responses
  - Prioritizes structured tool output over text parsing
  - Maintains backward compatibility for non-structured requests

### 4. Fixed Schema Format Handling
- **BatchService Integration Issue**:
  - BatchService was passing schema as: `[{'name': 'SchemaName', 'input_schema': {...}}]`
  - Provider expected: `{'type': 'object', 'properties': {...}}`
  - Added support for both formats with automatic detection
  
- **Dynamic Tool Naming**:
  - Tool names generated from schema names: `QuestionTypeSchema` → `questiontype_response`
  - Proper tool choice configuration: `{"type": "tool", "name": tool_name}`
  - Enhanced response parsing to handle dynamic tool names

### 5. Added Comprehensive Debug Logging
- **Schema Processing**: Shows which format is detected and processed
- **Tool Creation**: Confirms tools are created with correct properties
- **Response Parsing**: Tracks whether structured or text responses are received
- **Error Diagnostics**: Clear messages for troubleshooting schema issues

## What Was Done (Phase 4 - Configuration Consolidation)

### 1. Consolidated Provider Configuration Fields
- **Unified `model_vendor` Field**: 
  - Consolidated `model_vendor` and `batch_provider` fields to eliminate redundancy
  - `model_vendor` now controls both regular and batch processing provider selection
  - Supports all provider types: `"openai"`, `"gemini"`, `"anthropic"`, `"groq"`, `"tool"`

- **Backward Compatibility**: 
  ```python
  # BatchService now prioritizes model_vendor, falls back to batch_provider
  provider_type = agent_config.get('model_vendor', agent_config.get('batch_provider', 'openai'))
  
  # Deprecation warning logged when batch_provider is used without model_vendor
  if agent_config.get('batch_provider') and not agent_config.get('model_vendor'):
      print("⚠️ DEPRECATION WARNING: 'batch_provider' is deprecated. Use 'model_vendor' instead.")
  ```

- **Enhanced Validation**:
  - Added validation to prevent `'tool'` vendor from being used in batch mode
  - Clear error messages guide users to valid batch providers

### 2. Configuration Type Updates
- **Removed `batch_provider` field** from `AgentEntryDict` configuration type
- **Enhanced `model_vendor` documentation** to reflect its expanded role
- **Maintained all Anthropic-specific fields** (`anthropic_version`, `enable_prompt_caching`)

### 3. Documentation Updates
- **Updated all examples** to use `model_vendor` instead of `batch_provider`
- **Migration path documented** with clear before/after examples
- **Backward compatibility** assured during transition period

## What Was Done (Phase 5 - Legacy File System Cleanup)

### 1. Removed Global Batch File Dependencies
- **Eliminated `.last_batch_id` Files**:
  - Removed creation of global `{cwd}/batch/.last_batch_id` files
  - Removed fallback reads from global files in `_get_batch_job_id_for_file()`
  - Removed fallback reads from global files in `_get_last_batch_job_id()`
  - Cleaned up commented legacy code

- **Registry-Only Tracking**:
  ```python
  # Before: Mixed global + registry approach
  global_job_id_file = Path.cwd() / "batch" / ".last_batch_id"
  if global_job_id_file.exists():
      with open(global_job_id_file, 'r') as f:
          return f.read().strip()
  
  # After: Registry-only approach  
  registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
  # All tracking through registry - no global files
  ```

- **Documentation Updates**:
  - Updated batch README.md to emphasize registry-based system
  - Removed references to legacy global file system
  - Added multi-provider context to all examples
  
### 2. Enhanced Batch Architecture
- **Per-Workflow Isolation**: Each workflow maintains its own batch registry
- **No Global State**: Eliminated cross-workflow interference via global files  
- **Provider Tracking**: Registry now includes provider information per job
- **Better Debugging**: Clear separation between workflow-specific and legacy approaches

### 3. Backward Compatibility Maintained
- **CLI Commands Work**: `batch status` and `batch retrieve` still function
- **Registry Fallback**: `_get_last_batch_job_id()` uses registry for auto-detection
- **Existing Workflows**: No disruption to current batch processing workflows

## Configuration Migration

### Provider Consolidation (Before/After)
```yaml
# Before (Redundant)
agents:
  - agent_type: classifier
    model_vendor: "openai"      # ← Redundant
    batch_provider: "openai"    # ← Redundant  
    model_name: "gpt-4o-mini"
    run_mode: batch

# After (Clean)
agents:
  - agent_type: classifier
    model_vendor: "openai"      # ← Single source of truth
    model_name: "gpt-4o-mini"
    run_mode: batch
```

### Batch Tracking System (Before/After)
```bash
# Before (Global Files + Registry)
project/
├── batch/
│   └── .last_batch_id          # ← Global tracking file
└── workflows/
    └── my_workflow/
        └── batch/
            └── .batch_registry.json

# After (Registry-Only)  
project/
└── workflows/
    └── my_workflow/
        └── batch/
            └── .batch_registry.json    # ← Only tracking system
```

## What Comes Next

### 1. Additional Providers
Create new providers by implementing the `BatchProvider` interface:
- **AWS Bedrock Batch Inference**
- **Custom Internal APIs**
- **Azure OpenAI Batch API**

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
    model_vendor: openai
    model_name: "gpt-4o-mini"
    
batch_agent_2:
  - agent_type: classification
    run_mode: batch
    model_vendor: anthropic  # Different provider
    model_name: "claude-3-haiku"
    
batch_agent_3:
  - agent_type: summarization
    run_mode: batch
    model_vendor: openai
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
3. Update agent configuration with `model_vendor: your_provider`
4. Test with existing workflows

## Implementation Summary

### Current Status (Phase 5 Complete)
The batch processing system now supports three major providers through a clean, registry-based architecture:

- ✅ **OpenAI Batch Provider**: Original implementation with JSON mode support
- ✅ **Gemini Batch Provider**: Fully implemented and tested
- ✅ **Anthropic Batch Provider**: Complete with tool-based JSON mode
- ✅ **Provider Factory**: Dynamic provider instantiation for all three
- ✅ **BatchService Integration**: Multi-provider support with registry-only tracking
- ✅ **Configuration System**: Unified `model_vendor` field (deprecated `batch_provider`)
- ✅ **JSON Mode Support**: Structured output for all providers
- ✅ **Registry-Based Tracking**: No global file dependencies, per-workflow isolation
- ✅ **Error Handling**: Graceful dependency management and debugging
- ✅ **Documentation**: Complete usage, migration, and architecture guides

### Usage
Users can now specify different providers per agent with structured output:

```yaml
workflow: multi_provider_example
agents:
  - agent_type: classifier
    model_name: gpt-4o-mini
    model_vendor: openai
    run_mode: batch
    json_mode: true
    schema_name: ClassificationSchema
    
  - agent_type: enrichment  
    model_name: gemini-2.5-flash
    model_vendor: gemini
    run_mode: batch
    json_mode: true
    schema_name: EnrichmentSchema
    dependencies: [classifier]
    
  - agent_type: analyzer
    model_name: claude-3-5-sonnet-20241022
    model_vendor: anthropic
    run_mode: batch
    json_mode: true
    schema_name: AnalysisSchema
    dependencies: [enrichment]
```

### JSON Mode Implementation
Each provider handles structured output differently:

- **OpenAI**: Native `response_format: {"type": "json_object"}` 
- **Gemini**: Schema-guided generation with format instructions
- **Anthropic**: Tool use system with `tools` and `tool_choice` parameters

All providers return consistent `BatchResult` objects with structured content.

## What Was Done (Phase 6 - Anthropic Tool Use Fix)

### 1. Fixed Tool Use Response Parsing
- **Issue**: Tool use responses with non-standard names (e.g., 'quiz') were being converted to string representations like `"ToolUseBlock(id='...', input={...})"`
- **Root Cause**: The parser only accepted tools with names ending in '_response' or exactly matching 'json_response'
- **Fix**: Removed restrictive tool name checking to accept ALL tool use blocks

### 2. Implementation Changes
- **Updated Tool Name Matching** (`anthropic_provider.py`, lines 207-219):
  ```python
  # Before: Only accepted tools ending with '_response'
  if tool_name and ('_response' in tool_name or tool_name == 'json_response'):
  
  # After: Accept any tool use block
  if hasattr(content_block, 'input'):
      tool_use_content = content_block.input
  ```

- **Improved Fallback Handling** (lines 249-280):
  - Added detection for uncaught ToolUseBlock objects
  - Class name checking as last resort
  - Proper extraction of input data from any ToolUseBlock

- **Enhanced Debug Logging** (lines 236-248):
  - Log content type and structure
  - Show dictionary keys for debugging
  - Track JSON parsing success/failure

### 3. Results
- Tool use blocks with ANY name are now properly parsed
- Structured data is correctly extracted from tool inputs
- No more string representations of SDK objects in responses
- Maintains backward compatibility with existing '_response' tools

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