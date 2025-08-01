# Anthropic Batch Provider Implementation Plan

## Overview
This document outlines the implementation plan for adding Anthropic's Message Batches API as a batch provider in the agent-actions system. This will enable users to use Claude models for batch processing alongside existing OpenAI and Gemini providers.

## 1. API Analysis & Key Differences

### 1.1 Anthropic vs Other Providers

| Feature | OpenAI | Gemini | Anthropic |
|---------|--------|---------|-----------|
| **Submission Method** | File upload (JSONL) | File upload (JSONL) | Direct HTTP (JSON) |
| **Request Format** | `{custom_id, method, url, body}` | `{key, request}` | `{custom_id, params}` |
| **Max Batch Size** | ~50,000 requests | 10,000 requests | 100,000 requests or 256MB |
| **Processing Time** | Up to 24 hours | Up to 24 hours | Up to 24 hours (most < 1 hour) |
| **Results Retrieval** | Download file | Download file | Streaming API + Download |
| **System Messages** | Single string | Combined text | Array with caching support |
| **Schema Support** | Native JSON schema | Prompt-based | Prompt-based |
| **Cost Reduction** | 50% discount | 50% discount | 50% discount |

### 1.2 Anthropic-Specific Features

#### Advanced System Messages
```json
{
  "system": [
    {
      "type": "text",
      "text": "You are an AI assistant..."
    },
    {
      "type": "text", 
      "text": "<large context content>",
      "cache_control": {"type": "ephemeral"}
    }
  ]
}
```

#### Direct Submission Format
```json
{
  "requests": [
    {
      "custom_id": "request-1",
      "params": {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Hello"}]
      }
    }
  ]
}
```

#### Result Format
```json
{
  "custom_id": "request-1",
  "result": {
    "type": "succeeded",
    "message": {
      "content": [{"type": "text", "text": "Response..."}],
      "usage": {"input_tokens": 10, "output_tokens": 34}
    }
  }
}
```

### 1.3 Supported Models
- Claude Opus 4 (`claude-opus-4-20250514`)
- Claude Sonnet 4 (`claude-sonnet-4-20250514`) 
- Claude Sonnet 3.7 (`claude-3-7-sonnet-20250219`)
- Claude Sonnet 3.5 (`claude-3-5-sonnet-20240620`, `claude-3-5-sonnet-20241022`)
- Claude Haiku 3.5 (`claude-3-5-haiku-20241022`)
- Claude Haiku 3 (`claude-3-haiku-20240307`)
- Claude Opus 3 (`claude-3-opus-20240229`)

## 2. Implementation Architecture

### 2.1 Class Structure
```python
class AnthropicBatchProvider(BatchProvider):
    """
    Anthropic Message Batches API implementation.
    
    Key differences:
    - Direct HTTP submission (no file upload)
    - System message arrays with caching
    - Streaming results API
    - 4 result types: succeeded/errored/canceled/expired
    """
    
    def __init__(self, api_key: Optional[str] = None)
    def format_task_for_provider(self, batch_task: BatchTask, schema: Optional[Dict] = None) -> Dict
    def submit_batch(self, tasks: List[Dict], batch_name: str, output_directory: Optional[str] = None) -> str
    def check_status(self, batch_id: str) -> str
    def retrieve_results(self, batch_id: str, output_directory: Optional[str] = None) -> List[BatchResult]
    def parse_provider_response(self, raw_response: Any) -> BatchResult
    def compile_schema(self, schema_dict: Dict) -> Dict
    def get_supported_models(self) -> List[str]
    def supports_schema_validation(self) -> bool
```

### 2.2 Data Flow Transformation

#### Input Transformation
```python
# Our BatchTask format:
BatchTask(
    custom_id="123",
    prompt="Analyze this data",
    user_content='{"name": "John"}',
    model_config={"model_name": "claude-sonnet-4-20250514", "temperature": 0.1}
)

# Transforms to Anthropic format:
{
    "custom_id": "123", 
    "params": {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "system": "Analyze this data",
        "messages": [{"role": "user", "content": '{"name": "John"}'}],
        "temperature": 0.1
    }
}
```

#### Output Transformation
```python
# Anthropic result:
{
    "custom_id": "123",
    "result": {
        "type": "succeeded",
        "message": {
            "content": [{"type": "text", "text": '{"analysis": "result"}'}],
            "usage": {"input_tokens": 15, "output_tokens": 25}
        }
    }
}

# Transforms to our BatchResult:
BatchResult(
    custom_id="123",
    content={"analysis": "result"},  # Parsed JSON
    success=True,
    metadata={"model": "claude-sonnet-4-20250514"},
    usage={"input_tokens": 15, "output_tokens": 25}
)
```

## 3. Implementation Details

### 3.1 Core Methods Implementation

#### `format_task_for_provider()`
```python
def format_task_for_provider(self, batch_task: BatchTask, schema: Optional[Dict] = None) -> Dict:
    """Transform BatchTask to Anthropic format."""
    
    # Base parameters
    params = {
        "model": batch_task.model_config.get("model_name", "claude-sonnet-4-20250514"),
        "max_tokens": batch_task.model_config.get("max_tokens", 1024),
        "messages": [{"role": "user", "content": batch_task.user_content}]
    }
    
    # Add optional parameters
    if "temperature" in batch_task.model_config:
        params["temperature"] = batch_task.model_config["temperature"]
    
    # Handle system message
    if batch_task.prompt:
        system_messages = self._build_system_messages(
            batch_task.prompt, 
            schema,
            enable_caching=batch_task.model_config.get("enable_prompt_caching", False)
        )
        params["system"] = system_messages
    
    return {
        "custom_id": batch_task.custom_id,
        "params": params
    }

def _build_system_messages(self, prompt: str, schema: Optional[Dict], enable_caching: bool = False):
    """Build system message array with optional caching."""
    system_messages = []
    
    # Add main system prompt
    system_messages.append({
        "type": "text",
        "text": prompt
    })
    
    # Add schema instructions if provided
    if schema:
        schema_text = f"\n\nPlease respond with JSON that matches this schema:\n{json.dumps(schema, indent=2)}"
        system_messages.append({
            "type": "text", 
            "text": schema_text
        })
    
    # Enable caching on the last (largest) system message
    if enable_caching and system_messages:
        system_messages[-1]["cache_control"] = {"type": "ephemeral"}
    
    return system_messages if len(system_messages) > 1 else system_messages[0]["text"]
```

#### `submit_batch()`
```python
def submit_batch(self, tasks: List[Dict], batch_name: str, output_directory: Optional[str] = None) -> str:
    """Submit batch directly to Anthropic API (no file upload)."""
    
    try:
        # Submit directly to Anthropic
        response = self.client.messages.batches.create(requests=tasks)
        
        # Save batch metadata locally for tracking
        if output_directory:
            self._save_batch_metadata(response, batch_name, tasks, output_directory)
        
        print(f"Anthropic batch job created with ID: {response.id}")
        return response.id
        
    except Exception as e:
        raise RuntimeError(f"Error submitting Anthropic batch job: {e}")

def _save_batch_metadata(self, response, batch_name: str, tasks: List[Dict], output_directory: str):
    """Save batch metadata for local tracking."""
    batch_dir = Path(output_directory) / "batch"
    ensure_directory_exists(batch_dir)
    
    metadata = {
        "batch_id": response.id,
        "batch_name": batch_name,
        "provider": "anthropic",
        "created_at": response.created_at,
        "expires_at": response.expires_at,
        "request_count": len(tasks),
        "processing_status": response.processing_status
    }
    
    with open(batch_dir / f"{batch_name}_metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
```

#### `retrieve_results()`
```python
def retrieve_results(self, batch_id: str, output_directory: Optional[str] = None) -> List[BatchResult]:
    """Retrieve results using Anthropic's streaming API."""
    
    try:
        batch_results = []
        
        # Use Anthropic's streaming results API
        for result in self.client.messages.batches.results(batch_id):
            batch_result = self.parse_provider_response(result)
            batch_results.append(batch_result)
        
        # Save raw results if directory provided
        if output_directory:
            self._save_raw_results(batch_results, batch_id, output_directory)
        
        return batch_results
        
    except Exception as e:
        raise RuntimeError(f"Error retrieving Anthropic batch results: {e}")

def _save_raw_results(self, batch_results: List[BatchResult], batch_id: str, output_directory: str):
    """Save results in JSONL format for compatibility."""
    batch_dir = Path(output_directory) / "batch"
    ensure_directory_exists(batch_dir)
    
    result_file_path = batch_dir / f"{batch_id}_results.jsonl"
    
    with open(result_file_path, 'w') as f:
        for result in batch_results:
            # Convert to compatible format
            raw_format = {
                "custom_id": result.custom_id,
                "result": {
                    "type": "succeeded" if result.success else "errored",
                    "content": result.content,
                    "error": result.error,
                    "usage": result.usage
                }
            }
            f.write(json.dumps(raw_format) + '\n')
```

#### `parse_provider_response()`
```python
def parse_provider_response(self, raw_response) -> BatchResult:
    """Transform Anthropic result to BatchResult."""
    
    custom_id = raw_response.custom_id
    result = raw_response.result
    
    if result.type == "succeeded":
        # Extract content from message
        message = result.message
        content_text = ""
        
        if message.content and len(message.content) > 0:
            content_text = message.content[0].text
        
        # Try to parse as JSON, fallback to text
        try:
            content = json.loads(content_text)
        except json.JSONDecodeError:
            content = content_text
        
        return BatchResult(
            custom_id=custom_id,
            content=content,
            success=True,
            metadata={
                "model": message.model,
                "stop_reason": message.stop_reason,
                "message_id": message.id,
                "result_type": result.type
            },
            usage={
                "input_tokens": message.usage.input_tokens if message.usage else 0,
                "output_tokens": message.usage.output_tokens if message.usage else 0
            }
        )
    
    else:
        # Handle error/expired/canceled cases
        error_msg = self._format_error_message(result)
        
        return BatchResult(
            custom_id=custom_id,
            content=None,
            success=False,
            error=error_msg,
            metadata={"result_type": result.type}
        )

def _format_error_message(self, result) -> str:
    """Format error message based on result type."""
    if result.type == "errored" and hasattr(result, 'error'):
        return f"{result.error.type}: {result.error.message}"
    elif result.type == "expired":
        return "Request expired before processing"
    elif result.type == "canceled":
        return "Request was canceled"
    else:
        return f"Request failed with status: {result.type}"
```

### 3.2 Advanced Features

#### Multi-modal Support
```python
def _format_multimodal_content(self, user_content: str, attachments: Optional[List] = None):
    """Format content with potential image/file attachments."""
    
    if not attachments:
        return user_content
    
    # Build content array for multi-modal
    content_parts = [{"type": "text", "text": user_content}]
    
    for attachment in attachments:
        if attachment.get("type") == "image":
            content_parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": attachment["media_type"],
                    "data": attachment["data"]
                }
            })
        # Add support for other attachment types as needed
    
    return content_parts
```

#### Prompt Caching Optimization
```python
def _optimize_for_caching(self, tasks: List[Dict]) -> List[Dict]:
    """Optimize batch requests for prompt caching."""
    
    # Group tasks by similar system messages
    system_groups = {}
    for task in tasks:
        system_key = self._get_system_key(task["params"].get("system", ""))
        if system_key not in system_groups:
            system_groups[system_key] = []
        system_groups[system_key].append(task)
    
    # Apply caching to groups with multiple requests
    optimized_tasks = []
    for system_key, group_tasks in system_groups.items():
        if len(group_tasks) > 1:
            # Enable caching for this group
            for task in group_tasks:
                if isinstance(task["params"].get("system"), list):
                    # Add cache control to last system message
                    task["params"]["system"][-1]["cache_control"] = {"type": "ephemeral"}
        
        optimized_tasks.extend(group_tasks)
    
    return optimized_tasks
```

## 4. Integration Plan

### 4.1 Factory Integration
```python
# In factory.py
elif provider_type == "anthropic":
    api_key = config.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
    try:
        return AnthropicBatchProvider(api_key=api_key)
    except ImportError as e:
        raise ValueError(f"Anthropic provider not available: {e}")
```

### 4.2 Configuration Updates
```python
# In config_types.py - add Anthropic-specific fields
class AgentEntryDict(TypedDict, total=False):
    # ... existing fields ...
    anthropic_version: Optional[str]      # API version header
    enable_prompt_caching: Optional[bool] # Enable prompt caching
```

### 4.3 Dependency Management
```toml
# In pyproject.toml
anthropic = "^0.30.0"  # Add with version constraint
```

### 4.4 Graceful Import Handling
```python
# In anthropic_provider.py
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None

class AnthropicBatchProvider(BatchProvider):
    def __init__(self, api_key: Optional[str] = None):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package is not installed. "
                "Install it with: pip install anthropic"
            )
        
        self.client = anthropic.Anthropic(api_key=api_key)
```

## 5. Usage Examples

### 5.1 Basic Configuration
```yaml
agents:
  - agent_type: analysis
    name: claude_analyzer
    model_name: claude-sonnet-4-20250514
    batch_provider: anthropic
    run_mode: batch
    prompt: $analyze_data
    schema_name: analysis_results
    temperature: 0.1
    max_tokens: 2048
```

### 5.2 Advanced Configuration with Caching
```yaml
agents:
  - agent_type: literary_analysis
    name: claude_literature
    model_name: claude-opus-4-20250514
    batch_provider: anthropic
    run_mode: batch
    prompt: $literary_analysis_with_large_context
    enable_prompt_caching: true  # Enable caching for large prompts
    anthropic_version: "2023-06-01"
    temperature: 0.2
```

### 5.3 Multi-Provider Workflow
```yaml
workflow: comprehensive_analysis
agents:
  - agent_type: initial_classification
    model_name: gpt-4o-mini
    batch_provider: openai
    run_mode: batch
    
  - agent_type: deep_analysis
    model_name: claude-opus-4-20250514
    batch_provider: anthropic
    run_mode: batch
    dependencies: [initial_classification]
    enable_prompt_caching: true
    
  - agent_type: final_summary
    model_name: gemini-2.5-flash
    batch_provider: gemini
    run_mode: batch
    dependencies: [deep_analysis]
```

## 6. Testing Strategy

### 6.1 Unit Tests
- Test format transformations (BatchTask → Anthropic format)
- Test response parsing (Anthropic result → BatchResult)
- Test error handling for all 4 result types
- Test system message array building
- Test prompt caching optimization

### 6.2 Integration Tests
- Test full batch workflow with Anthropic API
- Test compatibility with existing BatchService
- Test multi-provider workflows
- Test graceful error handling when package missing

### 6.3 End-to-End Tests
- Test with actual Anthropic API (requires API key)
- Validate cost savings (50% reduction)
- Test with large batches (approaching limits)
- Test prompt caching effectiveness

## 7. Documentation Plan

### 7.1 User Documentation
Create `ANTHROPIC_BATCH.md` with:
- Installation instructions
- Configuration examples
- Feature comparison with other providers
- Prompt caching guide
- Multi-modal usage examples
- Troubleshooting guide

### 7.2 Migration Guide
- Converting from OpenAI to Anthropic
- Converting from Gemini to Anthropic
- Multi-provider best practices
- Cost optimization strategies

## 8. Implementation Timeline

### Phase 1: Core Implementation (Priority: High)
1. ✅ Create implementation plan document
2. Create AnthropicBatchProvider class
3. Implement core methods (format, submit, retrieve, parse)
4. Add graceful dependency handling
5. Basic integration testing

### Phase 2: Advanced Features (Priority: Medium)
6. System message arrays and prompt caching
7. Multi-modal content support
8. Batch optimization features
9. Comprehensive error handling

### Phase 3: Integration & Documentation (Priority: Medium)
10. Factory and configuration integration
11. Create user documentation
12. Add to CHANGES.md
13. End-to-end testing

## 9. Risk Assessment & Mitigation

### 9.1 Potential Risks
- **API Changes**: Anthropic API is relatively new, may have breaking changes
- **Rate Limits**: Different rate limiting compared to other providers
- **Dependency Issues**: New dependency might conflict with existing packages
- **Feature Gaps**: Some features may not be available immediately

### 9.2 Mitigation Strategies
- Pin specific anthropic package version
- Implement comprehensive error handling
- Provide fallback mechanisms
- Maintain backward compatibility
- Document known limitations clearly

## 10. Success Criteria

### 10.1 Functional Requirements
- ✅ Users can specify `batch_provider: anthropic` in configuration
- ✅ All BatchProvider interface methods implemented correctly
- ✅ Compatible with existing BatchService architecture
- ✅ Proper error handling and status reporting
- ✅ Results transformation matches expected format

### 10.2 Performance Requirements
- Batch submission completes successfully
- Results retrieval handles large result sets efficiently
- Memory usage remains reasonable for large batches
- Processing time competitive with other providers

### 10.3 Integration Requirements
- No breaking changes to existing functionality
- Multi-provider workflows work seamlessly
- Configuration system supports Anthropic-specific options
- Documentation is comprehensive and clear

---

**Next Steps**: Begin implementation starting with Phase 1, creating the core AnthropicBatchProvider class with graceful dependency handling.