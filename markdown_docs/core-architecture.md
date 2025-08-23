# Detailed Migration Guide: Exception System Overhaul

## Table of Contents
1. [Understanding the Old vs New System](#understanding-the-old-vs-new-system)
2. [New Exception Class Structure](#new-exception-class-structure)
3. [Error Context and Information Flow](#error-context-and-information-flow)
4. [Migration Process Step-by-Step](#migration-process-step-by-step)
5. [Practical Examples](#practical-examples)
6. [Testing Guide](#testing-guide)
7. [Troubleshooting](#troubleshooting)

## Understanding the Old vs New System

### Old System Architecture
```
┌─────────────────────────────────────┐
│ exceptions.py                       │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ Standard Python Exceptions      │ │
│ │ (FileNotFoundError, etc.)       │ │
│ └─────────────────────────────────┘ │
│                  │                  │
│                  ▼                  │
│ ┌─────────────────────────────────┐ │
│ │ Custom Exception Classes        │ │
│ │ (FileProcessingError, etc.)     │ │
│ └─────────────────────────────────┘ │
│                  │                  │
│                  ▼                  │
│ ┌─────────────────────────────────┐ │
│ │ Raise Helper Functions          │ │
│ │ (raise_file_processing_error)   │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│ Application Code                    │
├─────────────────────────────────────┤
│ try:                                │
│     # operation                     │
│ except Exception as e:              │
│     raise_file_processing_error(...)│
└─────────────────────────────────────┘
```

### New System Architecture
```
┌─────────────────────────────────────┐
│ exceptions.py                       │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ ErrorCategory Enum              │ │
│ └─────────────────────────────────┘ │
│                  │                  │
│                  ▼                  │
│ ┌─────────────────────────────────┐ │
│ │ ErrorContext Class              │ │
│ └─────────────────────────────────┘ │
│                  │                  │
│                  ▼                  │
│ ┌─────────────────────────────────┐ │
│ │ AgentError Base Class           │ │
│ └─────────────────────────────────┘ │
│                  │                  │
│                  ▼                  │
│ ┌─────────────────────────────────┐ │
│ │ Specialized Error Classes       │ │
│ │ (Hierarchical Structure)        │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│ error_utils.py                      │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ Decorators                      │ │
│ │ @handle_errors, @cli_command    │ │
│ └─────────────────────────────────┘ │
│                  │                  │
│                  ▼                  │
│ ┌─────────────────────────────────┐ │
│ │ Helper Functions                │ │
│ │ try_operation                   │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│ Application Code                    │
├─────────────────────────────────────┤
│ @handle_errors()                    │
│ def function():                     │
│     return try_operation(...)       │
└─────────────────────────────────────┘
```

## New Exception Class Structure

The new exception class hierarchy provides a logical organization of error types:

```
AgentError (Base)
│
├── SystemError
│   └── EnvironmentError
│
├── ConfigError
│   ├── MissingConfigError
│   ├── InvalidConfigError
│   ├── DuplicateConfigError
│   └── MissingSchemaError
│
├── WorkflowError
│   ├── WorkflowDefinitionError
│   ├── WorkflowExecutionError
│   └── WorkflowNameMismatchError
│
├── FileSystemError
│   ├── FileProcessingError
│   ├── NoFilesFoundError
│   └── DirectoryError
│
├── UserCodeError
│   ├── UDFNotFoundError
│   └── UDFExecutionError
│
├── ProjectError
│   ├── ProjectInitError
│   └── CleanupError
│
├── DocumentationError
│   ├── DocsServerError
│   └── TemplateRenderError
│
├── InternalError
│
├── UnhandledError
│
└── CliError
    ├── CliUsageError
    └── CliResultError
```

## Error Context and Information Flow

Each exception carries rich context through the `ErrorContext` class:

```
┌────────────────────────────────────────────┐
│ ErrorContext                               │
├────────────────────────────────────────────┤
│ message: str                               │ ◄─── Human-readable error message
│ error_code: str                            │ ◄─── Unique identifier for error type
│ category: ErrorCategory                    │ ◄─── General category of error
│ details: Dict[str, Any]                    │ ◄─── Additional contextual details
│ recovery_hint: Optional[str]               │ ◄─── Suggestion for recovery
│ traceback_str: Optional[str]               │ ◄─── Stack trace
│ exit_code: ExitCode                        │ ◄─── Process exit code
└────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────┐
│ AgentError                                 │
├────────────────────────────────────────────┤
│ context: ErrorContext                      │
└────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────┐
│ Error Handling Flow                        │
├────────────────────────────────────────────┤
│ 1. Error occurs                            │
│ 2. Exception created with context          │
│ 3. Handler receives rich error information │
│ 4. Formatted for logs/display              │
│ 5. Recovery hint provided to user          │
└────────────────────────────────────────────┘
```

## Migration Process Step-by-Step

### 1. Update Import Statements

**Before:**
```python
from agent_actions.core.exceptions import (
    raise_file_processing_error,
    raise_no_files_found_error
)
```

**After:**
```python
from agent_actions.core.exceptions import (
    FileProcessingError,
    NoFilesFoundError,
    ErrorCategory
)
from agent_actions.core.error_utils import try_operation, handle_errors
```

### 2. Apply Error Handling Decorators

**Before:**
```python
def process_file(file_path):
    # Function logic
```

**After:**
```python
@handle_errors()
def process_file(file_path):
    # Function logic
```

The `@handle_errors()` decorator wraps your function in a try/except block that:
- Passes through specified exception types
- Logs and re-raises AgentError exceptions
- Wraps unhandled exceptions in UnhandledError

### 3. Replace Direct Exception Raising

**Before:**
```python
try:
    # Some operation
except Exception as e:
    raise_file_processing_error(file_path, str(e))
```

**After:**
```python
try:
    # Some operation
except Exception as e:
    raise FileProcessingError(
        file_path=file_path,
        reason=str(e),
        recovery_hint="Check file permissions and contents"
    )
```

### 4. Use try_operation for Error-Prone Operations

**Before:**
```python
try:
    with open(file_path, 'r') as f:
        data = f.read()
    return process_data(data)
except Exception as e:
    raise_file_processing_error(file_path, str(e))
```

**After:**
```python
return try_operation(
    lambda: process_file_internal(file_path),
    f"Failed to process file: {file_path}",
    FileProcessingError,
    file_path=file_path
)

def process_file_internal(file_path):
    with open(file_path, 'r') as f:
        data = f.read()
    return process_data(data)
```

### 5. Update CLI Commands

**Before:**
```python
@main.command()
def init(project_name):
    try:
        # Initialize project
    except Exception as e:
        raise_project_init_error(project_name, str(e))
```

**After:**
```python
@main.command()
@cli_command
def init(project_name):
    try:
        # Initialize project
    except Exception as e:
        raise ProjectInitError(
            project_name=project_name,
            reason=str(e)
        )
```

The `@cli_command` decorator adds standardized error handling for CLI commands, properly formatting error messages and setting exit codes.

## Practical Examples

### Example 1: Simple File Processing

**Before:**
```python
def read_config_file(config_path):
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise_missing_config_error(config_path)
    except yaml.YAMLError as e:
        raise_invalid_config_format_error()
```

**After:**
```python
@handle_errors()
def read_config_file(config_path):
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise MissingConfigError(
            config_path=config_path,
            recovery_hint=f"Ensure the configuration file exists at {config_path}"
        )
    except yaml.YAMLError as e:
        raise InvalidConfigError(
            config_path=config_path,
            reason=f"Invalid YAML syntax: {str(e)}",
            recovery_hint="Check the YAML syntax in your configuration file"
        )
```

### Example 2: API with try_operation

**Before:**
```python
def get_agent_folder(current_dir, agent_name):
    agent_folder = FileHandler.find_specific_folder(
        current_dir, agent_name, 'agent_io'
    )
    if agent_folder is None:
        raise FileNotFoundError(f"Agent folder not found for agent: {agent_name}")
    return agent_folder
```

**After:**
```python
def get_agent_folder(current_dir, agent_name):
    agent_folder = try_operation(
        lambda: FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io'),
        f"Failed to find agent folder for agent {agent_name}",
        DirectoryError,
        directory=f"agent_io/{agent_name}"
    )
    
    if agent_folder is None:
        raise DirectoryError(
            directory=f"agent_io/{agent_name}",
            reason=f"Agent folder not found for agent: {agent_name}",
            recovery_hint=f"Create the agent folder for {agent_name}"
        )
    return agent_folder
```

### Example 3: Full Function Migration

**Before:**
```python
def execute_user_defined_function(udf_name, input_data):
    module_name, func_name = udf_name.rsplit('.', 1)
    
    try:
        module = importlib.import_module(module_name)
        udf = getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        raise_udf_not_found(func_name, module_name)

    try:
        result = udf(input_data)
        return result
    except Exception as e:
        raise_udf_execution_error(udf_name, str(e))
```

**After:**
```python
@handle_errors()
def execute_user_defined_function(udf_name, input_data):
    # Split the UDF name into module and function parts
    try:
        module_name, func_name = udf_name.rsplit('.', 1)
    except ValueError:
        raise UDFNotFoundError(
            function_name=udf_name,
            module_name="unknown",
            reason="Invalid UDF format. Expected 'module.function'"
        )
    
    # Load the function
    udf = load_user_defined_function(module_name, func_name)
    
    # Execute the function
    def _execute_function():
        try:
            return udf(input_data)
        except Exception as e:
            raise UDFExecutionError(
                function_name=func_name,
                reason=str(e)
            )
    
    return try_operation(
        _execute_function,
        f"Failed to execute function '{func_name}'",
        UDFExecutionError,
        function_name=func_name
    )
```

## Testing Guide

### 1. Testing Exception Types

```python
def test_file_not_found():
    # Arrange
    non_existent_path = "/path/to/nowhere"
    
    # Act & Assert
    with pytest.raises(MissingConfigError) as exc_info:
        read_config_file(non_existent_path)
    
    # Additional assertions on the exception context
    error = exc_info.value
    assert error.context.error_code == "MISSING_CONFIG"
    assert non_existent_path in error.context.details["config_path"]
```

### 2. Testing Error Context

```python
def test_invalid_config_format():
    # Arrange
    invalid_yaml_path = create_temp_file("key: : invalid")
    
    # Act & Assert
    with pytest.raises(InvalidConfigError) as exc_info:
        read_config_file(invalid_yaml_path)
    
    # Check error details
    error = exc_info.value
    assert error.category == ErrorCategory.CONFIGURATION
    assert "recovery_hint" in error.context.__dict__
    assert "YAML syntax" in error.context.recovery_hint
```

### 3. Testing CLI Commands

```python
from click.testing import CliRunner

def test_cli_init_command_error():
    # Arrange
    runner = CliRunner()
    
    # Act
    result = runner.invoke(main, ["init", "/invalid/path"])
    
    # Assert
    assert result.exit_code == ExitCode.PROJECT_INIT_ERROR.value
    assert "Failed to initialize project" in result.output
    assert "Hint:" in result.output  # Recovery hint should be present
```

## Troubleshooting

### Common Migration Issues

1. **Missing Error Classes**
   - **Problem**: Import error for a specific error class
   - **Solution**: Ensure you're importing from the new exceptions module

2. **Decorator Application Order**
   - **Problem**: Decorators not applying in the right order
   - **Solution**: Make sure `@handle_errors()` is the first decorator (closest to the function)

3. **Missing Exception Arguments**
   - **Problem**: Error when creating exceptions with missing required arguments
   - **Solution**: Check the constructor parameters for each error class in exceptions.py

4. **Unexpected Exception Wrapping**
   - **Problem**: Exceptions are being wrapped in UnhandledError unexpectedly
   - **Solution**: Use `excluded_types` parameter in the `@handle_errors()` decorator

```python
@handle_errors(excluded_types=[ValueError, TypeError])
def my_function():
    # These errors will not be wrapped
```

### When to Use Each Error Handling Approach

1. **Direct Exception Raising**:
   - When you need to report a specific error condition with custom details
   - When you're working within a try/except block that already handles other exceptions

2. **try_operation**:
   - For wrapping a single error-prone operation
   - When you want to provide consistent error messages and context

3. **@handle_errors Decorator**:
   - For functions that might raise various exceptions
   - To ensure all exceptions are properly handled and logged

4. **@cli_command Decorator**:
   - Always use for Click CLI command functions
   - Ensures proper error formatting and exit codes for command-line use