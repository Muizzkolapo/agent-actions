# Error Handling

Agent Actions provides a comprehensive error handling system designed to give developers clear, actionable error messages while maintaining robust internal error tracking. This guide covers the exception hierarchy, best practices, and testing strategies.

## Overview

The error handling system in Agent Actions follows these key principles:

1. **User-Friendly Errors**: Config users see clear, actionable messages without Python internals
2. **Developer Context**: Developers get full exception chains and debugging information
3. **Type Safety**: Domain-specific exceptions with proper type hints
4. **Exception Chaining**: Preserves root cause through multiple error levels
5. **Consistent Patterns**: Standard three-parameter pattern across all exceptions

## Exception Hierarchy

Agent Actions uses a hierarchical exception system where all custom exceptions inherit from `AgentActionsException`:

```
AgentActionsException (base)
├── ConfigurationError
│   ├── ConfigValidationError
│   └── EnvironmentConfigError
├── ProcessingError
│   ├── ValidationError
│   │   ├── SchemaValidationError
│   │   ├── PromptValidationError
│   │   └── DataValidationError
│   ├── TransformationError
│   ├── GenerationError
│   └── WorkflowError
├── ExternalServiceError
│   ├── VendorAPIError
│   │   ├── OpenAIError
│   │   ├── AnthropicError
│   │   └── GeminiError
│   ├── NetworkError
│   └── RateLimitError
├── ResourceError
│   ├── FileSystemError
│   │   ├── FileLoadError
│   │   ├── FileWriteError
│   │   └── DirectoryError
│   ├── MemoryError
│   └── DependencyError
└── OperationalError
    ├── AgentExecutionError
    ├── TemplateRenderingError
    └── SerializationError
```

### When to Use Each Exception Type

| Exception Type | Use When | Examples |
|---------------|----------|----------|
| `ConfigValidationError` | Configuration file has invalid values | Invalid model name, missing required field |
| `FileLoadError` | Cannot read a file | Config file not found, permission denied |
| `NetworkError` | Network/connection failure | API timeout, connection refused |
| `RateLimitError` | API rate limit exceeded | Too many requests to vendor |
| `ValidationError` | Data validation fails | Schema mismatch, invalid data format |
| `ProcessingError` | Data processing fails | Transformation error, generation failure |
| `AgentExecutionError` | Agent execution fails | Runtime error in agent logic |

## Standard Exception Pattern

All Agent Actions exceptions follow a consistent three-parameter pattern:

```python
raise SomeException(
    "Clear human-readable error message",
    context={'key1': 'value1', 'key2': 'value2'},
    cause=original_exception  # keyword-only, only when wrapping
)
```

### Constructor Signature

```python
def __init__(
    self,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    *,
    cause: Optional[Exception] = None
) -> None:
    """
    Args:
        message: Human-readable error message
        context: Dict with debugging context (file_path, operation, etc.)
        cause: Original exception when wrapping (keyword-only)
    """
```

**Key Points**:
- `message`: Required, human-readable description
- `context`: Optional dict with debugging information
- `cause`: Keyword-only parameter for exception chaining

## Creating Exceptions: Best Practices

### ✅ DO: Use Standard Pattern

#### 1. Configuration Error (No Cause)

```python
from agent_actions.core.exceptions import ConfigValidationError

def validate_model(config):
    valid_models = ['gpt-4o', 'claude-3-5-sonnet', 'gemini-1.5-pro']
    model = config.get('model')

    if model not in valid_models:
        raise ConfigValidationError(
            config_key="model",
            reason=f"Model '{model}' is not supported",
            context={
                'provided_value': model,
                'valid_models': valid_models,
                'agent_name': config.get('agent_name')
            }
        )
```

#### 2. File Error (With Cause)

```python
from agent_actions.core.exceptions import FileLoadError
import json

def load_config(file_path):
    try:
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError as e:
        raise FileLoadError(
            file_path=file_path,
            reason="Configuration file not found",
            context={
                'file_type': 'json',
                'operation': 'load_config'
            },
            cause=e
        )
    except json.JSONDecodeError as e:
        raise FileLoadError(
            file_path=file_path,
            reason="Invalid JSON syntax",
            context={
                'file_type': 'json',
                'operation': 'parse_json'
            },
            cause=e
        )
```

#### 3. Processing Error (With Cause)

```python
from agent_actions.core.exceptions import ProcessingError

def process_vendor_response(response, vendor_name):
    try:
        return vendor.parse_response(response)
    except Exception as e:
        raise ProcessingError(
            "Failed to process vendor API response",
            context={
                'vendor': vendor_name,
                'operation': 'parse_response',
                'response_status': response.status_code
            },
            cause=e
        )
```

#### 4. Network Error (With Cause)

```python
from agent_actions.core.exceptions import NetworkError
import socket

def call_api(endpoint, provider):
    try:
        response = requests.post(endpoint, timeout=60)
        return response.json()
    except socket.timeout as e:
        raise NetworkError(
            operation="api_call",
            reason="API request timed out after 60 seconds",
            context={
                'provider': provider,
                'endpoint': endpoint,
                'timeout_seconds': 60
            },
            cause=e
        )
    except ConnectionError as e:
        raise NetworkError(
            operation="api_call",
            reason="Failed to connect to API",
            context={
                'provider': provider,
                'endpoint': endpoint
            },
            cause=e
        )
```

### ❌ DON'T: Anti-Patterns to Avoid

#### 1. ❌ String Interpolation in Context

```python
# WRONG - context is a string
raise AgentActionsException(
    "Error occurred",
    f"File: {file_path}, Operation: {operation}"  # ❌ NOT a dict
)

# CORRECT - context is a dict
raise AgentActionsException(
    "Error occurred",
    context={'file_path': file_path, 'operation': operation}  # ✅ dict
)
```

#### 2. ❌ Missing Cause Parameter

```python
# WRONG - loses exception chain
try:
    process_file()
except IOError:
    raise AgentActionsException("Processing failed")  # ❌ Lost context

# CORRECT - preserves exception chain
try:
    process_file()
except IOError as e:
    raise AgentActionsException(
        "Processing failed",
        context={'file_path': file_path},
        cause=e  # ✅ Preserved
    )
```

#### 3. ❌ Positional Cause Parameter

```python
# WRONG - positional cause parameter
raise AgentActionsException("Error", context, e)  # ❌ Positional

# CORRECT - keyword-only cause parameter
raise AgentActionsException("Error", context, cause=e)  # ✅ Keyword-only
```

#### 4. ❌ Generic Exceptions

```python
# WRONG - generic Python exception
raise ValueError("Invalid model vendor")  # ❌ Generic

# CORRECT - domain-specific exception
raise ConfigValidationError(
    config_key="model_vendor",
    reason="Invalid model vendor",
    context={'provided_value': vendor}
)  # ✅ Domain-specific
```

## Exception Chaining

Exception chaining preserves the full error history from root cause to final error. This is critical for debugging complex workflows.

### How Chaining Works

When you raise an exception with `cause=original_exception`, Python maintains the exception chain:

```python
from agent_actions.core.exceptions import (
    ConfigValidationError,
    FileLoadError,
    AgentExecutionError
)

# Level 1: Root cause
def load_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError as e:
        raise FileLoadError(
            file_path=path,
            reason="Configuration file not found",
            cause=e  # Chain to FileNotFoundError
        )

# Level 2: Validation error
def validate_config(config_path):
    try:
        config = load_file(config_path)
        return json.loads(config)
    except FileLoadError as e:
        raise ConfigValidationError(
            config_key="config_file",
            reason="Cannot load configuration",
            context={'config_path': config_path},
            cause=e  # Chain to FileLoadError
        )

# Level 3: Execution error
def run_agent(agent_name):
    try:
        config = validate_config(f"configs/{agent_name}.json")
        return execute_agent(config)
    except ConfigValidationError as e:
        raise AgentExecutionError(
            f"Agent '{agent_name}' failed to start",
            context={'agent_name': agent_name},
            cause=e  # Chain to ConfigValidationError
        )
```

### Viewing Exception Chains

The error handling system provides utilities to view the full exception chain:

```python
from agent_actions.core.safe_format import (
    get_error_chain,
    extract_root_cause,
    format_exception_chain_for_debug
)

try:
    run_agent("my-agent")
except Exception as e:
    # Get all exceptions in the chain
    chain = get_error_chain(e)
    # chain = [AgentExecutionError, ConfigValidationError, FileLoadError, FileNotFoundError]

    # Get the root cause
    root = extract_root_cause(e)
    # root = FileNotFoundError

    # Format for debugging
    debug_output = format_exception_chain_for_debug(e)
    print(debug_output)
```

## User-Friendly Error Messages

Config users should never see Python stack traces or internal error details. The error handling system automatically translates exceptions to user-friendly messages.

### How It Works

```python
from agent_actions.core.user_errors import format_user_error

try:
    run_agent("quiz-gen")
except Exception as e:
    # For developers (with --debug flag)
    print(format_exception_chain_for_debug(e))

    # For users (normal mode)
    user_message = format_user_error(e, {
        "command": "run",
        "agent": "quiz-gen"
    })
    print(user_message)
```

### Example Transformation

**Before (Internal Error)**:
```
FileNotFoundError: [Errno 2] No such file or directory: '/configs/quiz-gen.json'
```

**After (User-Friendly)**:
```
Configuration Error: Agent configuration not found

  Agent: quiz-gen
  Expected: quiz-gen.json in configs directory
  Issue: Configuration file does not exist

  Available agents:
  • data-processor
  • content-writer
  • summarizer

  Fix: Either:
  1. Create configs/quiz-gen.json
  2. Use an existing agent: --agent data-processor

  Learn more: https://docs.agent-actions.com/agents
```

## Debug Mode

Use the `--debug` flag to see full exception chains and internal details:

```bash
# Normal mode (user-friendly errors)
agent-actions run --agent my-agent

# Debug mode (full exception chains)
agent-actions run --agent my-agent --debug
```

Debug mode shows:
- Full exception chain from root cause to final error
- File paths and line numbers
- Stack traces for each exception
- Context dictionaries at each level
- Structured logging output

## Testing Error Scenarios

### Testing Exception Creation

```python
import pytest
from agent_actions.core.exceptions import ConfigValidationError

def test_config_validation_error():
    """Test that ConfigValidationError captures context correctly."""
    with pytest.raises(ConfigValidationError) as exc_info:
        raise ConfigValidationError(
            config_key="model",
            reason="Invalid model name",
            context={'provided_value': 'invalid-model'}
        )

    exc = exc_info.value
    assert exc.context['config_key'] == 'model'
    assert exc.context['provided_value'] == 'invalid-model'
```

### Testing Exception Chaining

```python
import pytest
from agent_actions.core.exceptions import FileLoadError, ConfigValidationError
from agent_actions.core.safe_format import extract_root_cause

def test_exception_chaining():
    """Test that exception chains preserve root cause."""
    def level_1():
        raise FileNotFoundError("File not found")

    def level_2():
        try:
            level_1()
        except FileNotFoundError as e:
            raise FileLoadError(
                file_path="/config.json",
                reason="Cannot load file",
                cause=e
            )

    def level_3():
        try:
            level_2()
        except FileLoadError as e:
            raise ConfigValidationError(
                config_key="config",
                reason="Invalid configuration",
                cause=e
            )

    with pytest.raises(ConfigValidationError) as exc_info:
        level_3()

    # Verify root cause is preserved
    root = extract_root_cause(exc_info.value)
    assert isinstance(root, FileNotFoundError)
```

### Testing User-Friendly Messages

```python
import pytest
from agent_actions.core.exceptions import ConfigValidationError
from agent_actions.core.user_errors import format_user_error

def test_user_friendly_error_message():
    """Test that user sees friendly message without Python internals."""
    exc = ConfigValidationError(
        config_key="model",
        reason="Model not supported",
        context={'provided_value': 'gpt-5', 'agent': 'my-agent'}
    )

    user_message = format_user_error(exc, {"command": "run"})

    # Should contain user-friendly content
    assert "Configuration Error" in user_message
    assert "model" in user_message.lower()

    # Should NOT contain Python internals
    assert "ConfigValidationError" not in user_message
    assert "Traceback" not in user_message
```

### Testing Broken __str__ Methods

The error handling system is designed to never crash when formatting errors, even if the exception's `__str__` method is broken:

```python
import pytest
from agent_actions.core.safe_format import safe_format_error

def test_broken_str_method():
    """Test that safe_format_error handles broken __str__ methods."""
    class BrokenException(Exception):
        def __str__(self):
            raise RuntimeError("__str__ is broken")

    exc = BrokenException("Original message")

    # Should not crash, should fall back to repr()
    result = safe_format_error(exc)
    assert "BrokenException" in result
    assert "__str__ is broken" not in result
```

## Integration Testing

Integration tests verify that error handling works correctly in real-world scenarios:

```python
import pytest
from agent_actions.core.exceptions import NetworkError, RateLimitError
from agent_actions.core.user_errors import format_user_error

def test_network_error_integration():
    """Test network error scenario end-to-end."""
    def simulate_api_call():
        raise ConnectionError("Failed to connect to api.anthropic.com")

    with pytest.raises(NetworkError) as exc_info:
        try:
            simulate_api_call()
        except ConnectionError as e:
            raise NetworkError(
                operation="create_message",
                reason="Failed to connect to AI provider",
                context={'provider': 'anthropic'},
                cause=e
            )

    # Format for user
    user_message = format_user_error(exc_info.value, {"command": "run"})

    # Verify user-friendly output
    assert "network" in user_message.lower()
    assert "anthropic" in user_message.lower()
    assert "ConnectionError" not in user_message  # No Python internals
```

See the full test suite for more examples:
- `tests/core/test_exceptions.py` - Exception formatting tests (16 tests)
- `tests/core/test_safe_format.py` - Safe formatting utilities (21 tests)
- `tests/core/test_context_preservation.py` - Exception chaining tests (19 tests)
- `tests/integration/test_error_handling_integration.py` - Real-world scenarios (21 tests)

## Quick Reference

### Common Exceptions

```python
from agent_actions.core.exceptions import (
    ConfigValidationError,    # Invalid config value
    FileLoadError,            # Cannot read file
    FileWriteError,           # Cannot write file
    NetworkError,             # Connection/network issue
    RateLimitError,           # API rate limit exceeded
    ProcessingError,          # Data processing failed
    AgentExecutionError,      # Agent runtime error
    ValidationError,          # Data validation failed
    SchemaValidationError,    # Schema validation failed
)
```

### Key Functions

```python
from agent_actions.core.safe_format import (
    safe_format_error,                  # Format any exception safely
    extract_root_cause,                 # Get root cause from chain
    get_error_chain,                    # Get all exceptions in chain
    format_exception_chain_for_debug    # Format chain for debugging
)

from agent_actions.core.user_errors import (
    format_user_error                   # Convert to user-friendly message
)
```

## Best Practices Summary

1. ✅ **Always use domain-specific exceptions** (ConfigValidationError, not ValueError)
2. ✅ **Always pass context as a dict** (never as a string)
3. ✅ **Always use cause parameter** when wrapping exceptions
4. ✅ **Always use keyword-only cause** (`cause=e`, not positional)
5. ✅ **Include operation context** in every exception
6. ✅ **Test error scenarios** with pytest
7. ✅ **Use --debug flag** for development debugging
8. ✅ **Never expose Python internals** to config users

## Related Documentation

- [Agents](./agents.md) - Agent configuration and execution
- [Workflows](./workflows.md) - Workflow error handling
- [Schemas](./schemas.md) - Schema validation errors
- [CLI Reference](../cli-reference.md) - Command-line error handling
