# Anthropic Batch Provider Documentation

## Overview

The Anthropic Batch Provider integrates with Anthropic's Message Batches API to enable efficient batch processing of Claude model requests within the agent-actions framework. This provider supports all Claude models available through the Message Batches API.

## Features

- **Direct HTTP Submission**: No file upload required - requests are submitted directly via HTTP
- **Streaming Results**: Real-time retrieval of batch results as they become available
- **Prompt Caching**: Optional support for Anthropic's prompt caching feature
- **System Message Arrays**: Support for complex prompt structures with system messages
- **Real-time Status Checking**: Monitor batch progress with detailed status information
- **Structured Output**: Guided structured output through natural language prompting

## Supported Models

The Anthropic provider supports the following Claude models for batch processing:

* Claude Opus 4 (`claude-opus-4-20250514`)
* Claude Sonnet 4 (`claude-sonnet-4-20250514`)
* Claude Sonnet 3.7 (`claude-3-7-sonnet-20250219`)
* Claude Sonnet 3.5 (`claude-3-5-sonnet-20240620` and `claude-3-5-sonnet-20241022`)
* Claude Haiku 3.5 (`claude-3-5-haiku-20241022`)
* Claude Haiku 3 (`claude-3-haiku-20240307`)
* Claude Opus 3 (`claude-3-opus-20240229`)

## Configuration

### Agent Configuration

Configure an agent to use the Anthropic batch provider:

```json
{
  "agent_name": "my_anthropic_agent",
  "model_vendor": "anthropic",
  "model_name": "claude-3-5-sonnet-20241022",
  "temperature": 0.1,
  "max_tokens": 1024,
  "anthropic_version": "2023-06-01",
  "enable_prompt_caching": false,
  "prompt": "Your system prompt here..."
}
```

### Configuration Fields

- **model_vendor**: Must be set to `"anthropic"` (replaces deprecated `batch_provider`)
- **model_name**: Claude model to use (see supported models above)

> **Note**: The `batch_provider` field is deprecated. Use `model_vendor` for unified provider configuration.
- **anthropic_version**: API version header (optional, defaults to "2023-06-01")
- **enable_prompt_caching**: Enable prompt caching feature (optional, defaults to false)

### Environment Variables

Set your Anthropic API key as an environment variable:

```bash
export ANTHROPIC_API_KEY="your_anthropic_api_key_here"
```

Alternatively, you can pass the API key directly in the configuration:

```json
{
  "api_key": "your_anthropic_api_key_here"
}
```

## API Format Differences

### Input Format

The Anthropic provider transforms our standard format to Anthropic's Message Batches API format:

**Agent-Actions Format:**
```json
{
  "target_id": "request_123",
  "content": {
    "user_input": "Process this data...",
    "context": "Additional context"
  }
}
```

**Anthropic API Format:**
```json
{
  "custom_id": "request_123",
  "params": {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "system",
        "content": "Your system prompt here..."
      },
      {
        "role": "user",
        "content": "{\"user_input\": \"Process this data...\", \"context\": \"Additional context\"}"
      }
    ]
  }
}
```

### Output Format

**Anthropic API Response:**
```json
{
  "custom_id": "request_123",
  "result": {
    "type": "succeeded",
    "message": {
      "content": [{"type": "text", "text": "Response content"}],
      "role": "assistant",
      "model": "claude-3-5-sonnet-20241022",
      "stop_reason": "end_turn",
      "usage": {
        "input_tokens": 150,
        "output_tokens": 75
      }
    }
  }
}
```

**Transformed to BatchResult:**
```python
BatchResult(
    custom_id="request_123",
    content="Response content",  # or parsed JSON if structured
    success=True,
    error=None,
    metadata={
        "model": "claude-3-5-sonnet-20241022",
        "stop_reason": "end_turn",
        "anthropic_version": "2023-06-01",
        "result_type": "succeeded"
    },
    usage={
        "input_tokens": 150,
        "output_tokens": 75
    }
)
```

## Usage Examples

### Basic Batch Processing

```python
from agent_actions.providers.factory import BatchProviderFactory
from agent_actions.providers.base import BatchTask
import os

# Set up API key
os.environ["ANTHROPIC_API_KEY"] = "your_api_key"

# Create provider
provider = BatchProviderFactory.create_provider("anthropic")

# Prepare data
data = [
    {
        "target_id": "task_1",
        "content": {"text": "Analyze this sentiment: I love this product!"}
    },
    {
        "target_id": "task_2", 
        "content": {"text": "Analyze this sentiment: This is terrible."}
    }
]

# Agent configuration
agent_config = {
    "model_name": "claude-3-5-sonnet-20241022",
    "prompt": "Analyze the sentiment of the following text and respond with 'positive', 'negative', or 'neutral':",
    "temperature": 0.1,
    "max_tokens": 50
}

# Submit batch
tasks = provider.prepare_tasks(data, agent_config)
batch_id = provider.submit_batch(tasks, "sentiment_analysis_batch")

# Monitor status
status = provider.check_status(batch_id)
print(f"Batch status: {status}")

# Retrieve results when completed
if status == "completed":
    results = provider.retrieve_results(batch_id)
    for result in results:
        print(f"ID: {result.custom_id}, Result: {result.content}")
```

### With Prompt Caching

```python
# Enable prompt caching for large system prompts
config = {
    "enable_prompt_caching": True,
    "anthropic_version": "2023-06-01"
}

provider = BatchProviderFactory.create_provider("anthropic", config)
```

### Structured Output

```python
agent_config = {
    "model_name": "claude-3-5-sonnet-20241022",
    "prompt": """Analyze the following text and respond with a JSON object containing:
    - sentiment: "positive", "negative", or "neutral"
    - confidence: a number between 0 and 1
    - key_phrases: array of important phrases""",
    "temperature": 0.1,
    "max_tokens": 200
}
```

## Error Handling

### Common Errors

1. **Authentication Error**: Invalid API key
```python
# Error: "Anthropic authentication failed: Invalid API key"
# Solution: Check your ANTHROPIC_API_KEY environment variable
```

2. **Model Not Supported**: Using unsupported model
```python
# Error: "Model 'gpt-4' is not supported by Anthropic batch processing"
# Solution: Use a supported Claude model
```

3. **API Rate Limits**: Too many requests
```python
# Error: "Anthropic API error during batch submission: Rate limit exceeded"
# Solution: Implement retry logic or reduce batch size
```

### Error Response Format

Failed batch items return structured error information:

```python
BatchResult(
    custom_id="failed_task",
    content=None,
    success=False,
    error="Input too long: maximum context length exceeded",
    metadata={
        "result_type": "failed",
        "error_info": {"type": "input_too_long", "message": "..."}
    }
)
```

## Status Monitoring

### Status Values

- `in_progress`: Batch is being processed
- `completed`: All tasks completed successfully
- `failed`: Batch processing failed
- `cancelled`: Batch was cancelled

### Polling Example

```python
import time

def wait_for_completion(provider, batch_id, max_wait=3600):
    """Wait for batch completion with timeout."""
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        status = provider.check_status(batch_id)
        print(f"Status: {status}")
        
        if status == "completed":
            return provider.retrieve_results(batch_id)
        elif status in ["failed", "cancelled"]:
            raise RuntimeError(f"Batch {batch_id} {status}")
        
        time.sleep(30)  # Check every 30 seconds
    
    raise TimeoutError(f"Batch {batch_id} did not complete within {max_wait} seconds")
```

## Best Practices

### 1. Batch Size Optimization
- Start with smaller batches (50-100 tasks) to test your configuration
- Gradually increase batch size based on your use case
- Monitor for rate limits and adjust accordingly

### 2. Prompt Design
- Use clear, specific prompts for consistent results
- For structured output, provide detailed format instructions
- Test prompts with individual requests before batching

### 3. Error Recovery
- Always check batch status before retrieving results
- Implement retry logic for failed submissions
- Handle partial failures gracefully

### 4. Resource Management
- Store batch IDs for long-running jobs
- Clean up output files periodically
- Monitor API usage and costs

## Integration with Existing Workflows

The Anthropic provider seamlessly integrates with existing agent-actions workflows:

```python
# In your existing batch service code
batch_service = BatchService()

# The service will automatically use Anthropic if configured
results = batch_service.run_batch_on_data(
    data=your_data,
    agent_config={
        "model_vendor": "anthropic",  # Unified provider field
        "model_name": "claude-3-5-sonnet-20241022",
        # ... other config
    }
)
```

## Troubleshooting

### Installation Issues
```bash
# Ensure anthropic package is installed
pip install anthropic>=0.30.0

# Verify installation
python -c "import anthropic; print('Anthropic installed successfully')"
```

### API Key Issues
```bash
# Test API key
export ANTHROPIC_API_KEY="your_key"
python -c "
import anthropic
client = anthropic.Anthropic()
print('API key valid')
"
```

### Debug Mode
Enable debug logging to troubleshoot issues:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Provider will now output detailed debug information
```

## Cost Considerations

- Anthropic charges based on input and output tokens
- Batch processing may have different pricing than real-time API calls
- Use `max_tokens` to control output length and costs
- Monitor usage through the Anthropic console

## Migration from Other Providers

When migrating from OpenAI or other providers:

1. **Update agent configuration**: Change `model_vendor` to `"anthropic"` (unified field)
2. **Remove legacy fields**: Remove `batch_provider` if present (deprecated)
3. **Model names**: Update to Claude model names
4. **Prompt adjustments**: Claude may interpret prompts differently
5. **Output format**: Review and adjust result parsing if needed

## Support and Resources

- [Anthropic Message Batches API Documentation](https://docs.anthropic.com/en/docs/build-with-claude/message-batches)
- [Claude Model Documentation](https://docs.anthropic.com/en/docs/models-overview)
- [Anthropic Console](https://console.anthropic.com/)


