# Agent Actions - Feature Documentation

## 🎯 Core Features Overview

Agent Actions is a powerful framework for building, orchestrating, and managing AI agent workflows with advanced validation, reprompting, and batch processing capabilities.

## 1. 🔄 Interceptors & Validation System

### Validation Interceptors
- **Built-in Validators**:
  - `word_count`: Exact word count validation
  - `char_count`: Character count range validation
  - `contains_keywords`: Required keywords validation
- **Custom Validators**: Create custom validation functions and reference them by module path
- **Validation Actions**: `retry`, `fail`, or `continue` on validation failure
- **Artifact Recording**: Automatic tracking of validation attempts and results

### Reprompt Interceptors
- **Strategies**:
  - **LLM Strategy**: Uses AI to analyze failures and generate improved prompts
  - **Simple Strategy**: Basic template-based reprompting with configurable options
  - **Template Strategy**: Pattern-based templates matched to specific error types
- **Configuration Options**:
  - `max_attempts`: Limit retry attempts (default: 3)
  - `include_previous_response`: Include failed response in reprompt context
  - `prompt_debug`: Enable detailed debugging output

### Example Configuration
```yaml
interceptors:
  - type: validation
    validator_function: "agent_actions.validators.builtin_functions.word_count_validator"
    validator_args:
      expected: 19
    on_failure: retry
    
  - type: reprompt
    strategy: "simple"
    max_attempts: 5
    include_previous_response: true
```

## 2. 🚀 Workflow & Pipeline Features

### Async/Parallel Execution
- **Parallel Agent Execution**: Run multiple agents concurrently with `async_run()`
- **Concurrency Limiting**: Control parallel execution with semaphore-based limits
- **Batch Processing**: Efficient batch API calls with provider-specific optimizations

### Workflow Management
- **Execution Order Control**: Define agent execution sequence
- **Conditional Execution**: Skip agents based on WHERE clause conditions
- **Status Tracking**: Real-time agent status monitoring (pending/in_progress/completed/failed)
- **Ephemeral Directories**: Manage temporary output directories with automatic cleanup

### Pipeline Features
- **Multi-Stage Processing**: Chain agents in complex pipelines
- **Data Lineage Tracking**: Automatic tracking of data transformations through nodes
- **Passthrough Support**: Skip processing while preserving data structure

## 3. 📝 Template & Rendering System

### Jinja2 Template Integration
- **YAML Templating**: Use Jinja2 templates in configuration files
- **Macro Support**: Define reusable configuration snippets
- **Dynamic Prompt Loading**: Reference prompts with `$prompt_key` syntax
- **Template Resolution**: Automatic template file discovery and loading

### Prompt Management
- **Prompt Store**: Centralized prompt management system
- **Dynamic Loading**: Runtime prompt resolution with `PromptLoader`
- **Nested References**: Support for complex prompt hierarchies
- **Template Variables**: Pass context variables to prompts

## 4. 🏗️ Configuration Management

### Hierarchical Configuration
- **Constructor Path**: Base configuration templates
- **User Code Path**: Custom user configurations
- **Default Path**: Fallback configurations
- **Override Mechanism**: Layer-based configuration merging

### Environment Support
- **Multiple Environments**: Dev, staging, production configurations
- **Environment Variables**: Dynamic configuration via environment
- **Secret Management**: Secure handling of API keys and credentials

## 5. 📊 Artifact System

### Comprehensive Tracking
- **Manifest Management**: Track all workflow artifacts
- **Validation Results**: Store validation attempts and outcomes
- **Run Results**: Complete execution history
- **Security Features**: Built-in security checks and access controls

### Data Persistence
- **JSON Storage**: Structured data storage in JSON format
- **Catalog System**: Organize and retrieve artifacts efficiently
- **Context Management**: Thread-safe artifact context handling

## 6. 🔧 Batch Processing

### Provider Support
- **OpenAI Batch API**: Native support for OpenAI batch processing
- **Anthropic Integration**: Batch support for Claude models
- **Gemini Support**: Google AI batch processing
- **Custom Providers**: Extensible provider system

### Batch Features
- **Task Bundling**: Automatic grouping of similar tasks
- **Cost Optimization**: Leverage provider batch pricing
- **Progress Tracking**: Monitor batch job status
- **Error Recovery**: Automatic retry and error handling

## 7. 🛡️ Resilience & Error Handling

### Retry Mechanisms
- **Exponential Backoff**: Smart retry with increasing delays
- **Circuit Breaker**: Prevent cascading failures
- **Custom Retry Policies**: Configure retry behavior per agent

### Error Management
- **Detailed Error Context**: Comprehensive error information
- **Graceful Degradation**: Continue processing on partial failures
- **Error Aggregation**: Collect and report multiple errors

## 8. 🔍 Filtering & Conditionals

### WHERE Clause Support
- **SQL-like Syntax**: Familiar conditional expressions
- **Safe Evaluation**: Secure expression parsing
- **Global Filters**: Apply filters across entire workflow
- **Skip Conditions**: Conditionally bypass agents

### Data Transformation
- **Built-in Transformers**: Common data transformation utilities
- **Custom Functions**: User-defined transformation functions
- **Collection Operations**: Filter, map, reduce operations

## 9. 🎨 Vendor & Model Support

### Multi-Vendor Integration
- **OpenAI**: GPT-3.5, GPT-4, and custom models
- **Anthropic**: Claude models
- **Google**: Gemini models
- **Mistral**: Open-source model support
- **Ollama**: Local model execution
- **Groq**: High-performance inference

### Model Configuration
- **Dynamic Selection**: Runtime model selection
- **Fallback Models**: Automatic failover to backup models
- **Cost Tracking**: Monitor API usage and costs

## 10. 🔌 Extensibility

### Plugin System
- **Custom Validators**: Add domain-specific validation
- **Custom Interceptors**: Extend processing pipeline
- **Custom Providers**: Integrate new AI services
- **Hook System**: Pre/post processing hooks

### Integration Points
- **REST API Support**: External service integration
- **Webhook Handlers**: Event-driven processing
- **Database Connectors**: Direct data source access
- **Message Queues**: Async task distribution

## 11. 📈 Monitoring & Observability

### Logging System
- **Structured Logging**: JSON-formatted logs
- **Log Levels**: Configurable verbosity
- **Performance Metrics**: Execution time tracking
- **Resource Usage**: Memory and CPU monitoring

### Debug Features
- **Prompt Debug Mode**: Detailed prompt execution traces
- **Validation Debug**: Step-by-step validation output
- **Workflow Visualization**: Visual workflow representation

## 12. 🔐 Security Features

### Access Control
- **Path Validation**: Secure file system access
- **Input Sanitization**: Protection against injection attacks
- **Secret Masking**: Automatic credential redaction in logs

### Compliance
- **Audit Trails**: Complete operation history
- **Data Encryption**: Secure data storage
- **GDPR Support**: Data privacy compliance features

## Usage Examples

### Basic Agent with Validation
```yaml
agents:
  - agent_type: ContentGenerator
    interceptors:
      - type: validation
        validator_function: "agent_actions.validators.builtin_functions.word_count_validator"
        validator_args:
          expected: 100
      - type: reprompt
        strategy: "simple"
        max_attempts: 3
```

### Parallel Workflow Execution
```python
workflow = AgentWorkflow(config_path)
await workflow.async_run(concurrency_limit=5)
```

### Custom Validator Functions
```python
# Create your custom validator function
def validate_domain(content: str, domain: str) -> Tuple[bool, str]:
    if domain in content:
        return True, None
    return False, f"Missing domain: {domain}"
```

Then reference it in your YAML configuration:
```yaml
interceptors:
  - type: validation
    config:
      validator_function: "your_module.validate_domain"
      validator_args:
        domain: "example.com"
      on_failure: retry
```

## Best Practices

1. **Start with built-in validators** before creating custom ones
2. **Use templates for consistent configurations** across environments
3. **Enable prompt_debug during development** for better visibility
4. **Set reasonable max_attempts** to prevent infinite loops
5. **Implement circuit breakers** for external service calls
6. **Use batch processing** for cost optimization with large datasets
7. **Track artifacts** for debugging and audit purposes
8. **Layer configurations** for environment-specific settings

## Advanced Features (Coming Soon)

- **Visual Workflow Designer**: GUI for creating agent workflows
- **Real-time Collaboration**: Multi-user workflow editing
- **Advanced Analytics**: Detailed performance analytics dashboard
- **Model Fine-tuning Integration**: Direct integration with fine-tuning pipelines
- **Distributed Execution**: Scale across multiple machines
- **GraphQL API**: Flexible query interface for artifacts