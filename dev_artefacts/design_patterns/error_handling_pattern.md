# Error Handling Design Pattern

## Pattern Name: Context-Aware Error Handling

### Problem Statement
Users of config-driven CLI tools should never see Python stack traces or internal implementation details. They need clear, actionable error messages about their configuration files, similar to tools like dbt or Terraform.

### Current Issues
- 20+ files using unsafe `str(e)` calls that can cascade failures
- Inconsistent error handling across 8 CLI commands
- Dual exception systems (core/exceptions.py vs cli/exceptions.py)
- Users see Python internals like `'str' object has no attribute 'items'`

### Solution Overview
A standardized pattern using decorators for context capture and handlers for consistent error formatting across the entire codebase.

---

## Core Components

### 1. Error Context Decorator
**File:** `agent_actions/core/error_context.py`

```python
from functools import wraps
from typing import Any, Callable, Dict
import inspect

def with_error_context(**context_kwargs):
    """
    Decorator that automatically enriches exceptions with context.

    Usage:
        @with_error_context(operation="load_config", resource_type="agent")
        def load_agent_config(agent_name: str):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Auto-extract context from function signature
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            context = {
                'function': func.__name__,
                'module': func.__module__,
                **context_kwargs,
                **{k: v for k, v in bound_args.arguments.items()
                   if k in ['agent_name', 'file_path', 'config_name', 'model', 'provider']}
            }

            try:
                return func(*args, **kwargs)
            except Exception as e:
                if not hasattr(e, 'error_context'):
                    e.error_context = {}
                e.error_context.update(context)
                raise

        return wrapper
    return decorator
```

### 2. Standard Error Handler
**File:** `agent_actions/core/error_handler.py`

```python
class StandardErrorHandler:
    """Base error handler for consistent error handling."""

    def __init__(self, module_name: str):
        self.module_name = module_name
        self.logger = logging.getLogger(module_name)

    def handle(self, error: Exception, fallback_message: str = None) -> str:
        """Convert exception to user-friendly message."""
        context = getattr(error, 'error_context', {})

        # Log for debugging
        self.logger.error(f"Error in {self.module_name}", exc_info=True, extra={'context': context})

        # Generate user message
        return self.create_user_message(error, context, fallback_message)

    def create_user_message(self, error: Exception, context: Dict[str, Any], fallback: str = None) -> str:
        """Override in subclasses for custom messages."""
        if fallback:
            return fallback

        operation = context.get('operation', 'operation').replace('_', ' ')
        resource = context.get('resource_type', 'resource')

        message_parts = [f"Failed to {operation}"]

        if 'agent_name' in context:
            message_parts.append(f"for agent '{context['agent_name']}'")
        elif 'file_path' in context:
            message_parts.append(f"for file '{context['file_path']}'")

        return " ".join(message_parts)
```

---

## Implementation Patterns

### Pattern 1: Function Decoration
Every function that can fail should be decorated:

```python
@with_error_context(operation="process", resource_type="agent")
def process_agent(agent_name: str, config: Dict):
    # Function implementation
    pass
```

### Pattern 2: Exception Handling
All exception handlers follow this pattern:

```python
error_handler = StandardErrorHandler(__name__)

try:
    result = do_something()
except Exception as e:
    user_message = error_handler.handle(e)
    # Use user_message for display
```

### Pattern 3: CLI Commands
All CLI commands follow this structure:

```python
@click.command()
def command_name(args):
    try:
        # Command logic
        pass
    except UserFriendlyError as e:
        click.echo(f"Error: {e.user_message}", err=True)
        raise click.Abort()
    except Exception as e:
        user_error = error_handler.wrap_for_cli(e)
        click.echo(f"Error: {user_error.user_message}", err=True)
        if '--debug' in sys.argv:
            traceback.print_exc()
        raise click.Abort()
```

---

## Usage Examples

### Example 1: Agent Processing

```python
# agent_actions/agents/processors/config_processor.py

from agent_actions.core.error_context import with_error_context
from agent_actions.core.error_handler import StandardErrorHandler

error_handler = StandardErrorHandler(__name__)

class ConfigProcessor:

    @with_error_context(operation="load_config", resource_type="config")
    def load_config(self, agent_name: str) -> Dict:
        with open(f"agents/{agent_name}.yaml") as f:
            return yaml.safe_load(f)

    @with_error_context(operation="validate_config", resource_type="config")
    def validate_config(self, config: Dict, schema: Dict):
        # Validation logic
        pass

    def process(self, agent_name: str):
        try:
            config = self.load_config(agent_name)
            self.validate_config(config, self.schema)
            return config
        except Exception as e:
            message = error_handler.handle(e)
            raise UserFriendlyError(message) from e
```

### Example 2: CLI Command

```python
# agent_actions/tasks/run.py

from agent_actions.core.error_handler import CLIErrorHandler
import click

error_handler = CLIErrorHandler(__name__)

@click.command()
@click.option('-a', '--agent', required=True)
def run(agent):
    """Run an agent with proper error handling."""
    try:
        runner = AgentRunner()
        runner.execute(agent)
    except Exception as e:
        user_error = error_handler.wrap_for_cli(e)
        click.echo(f"Error: {user_error.user_message}", err=True)
        raise click.Abort()
```

### Example 3: API Provider

```python
# agent_actions/integrations/providers/anthropic/provider.py

from agent_actions.core.error_context import with_api_context

class AnthropicProvider:

    @with_api_context(provider="anthropic")
    def submit_batch(self, requests: List[Dict]) -> str:
        response = self.client.submit_batch(requests)
        return response.batch_id
```

---

## Migration Guide

### Phase 1: Core Setup (2 hours)
1. Create `agent_actions/core/error_context.py`
2. Create `agent_actions/core/error_handler.py`
3. Add safe_format_error() utility

### Phase 2: Pilot Implementation (2 hours)
1. Choose one CLI command (recommend: `tasks/run.py`)
2. Add decorators to all functions
3. Replace exception handling with pattern
4. Test thoroughly

### Phase 3: Rollout (8-10 hours)
1. Update remaining CLI commands
2. Add decorators to agent processors
3. Update provider integrations
4. Replace all `str(e)` calls

### Phase 4: Validation (2 hours)
1. Add unit tests for error scenarios
2. Manual testing of user flows
3. Update documentation

---

## Benefits

1. **Consistency**: Same pattern everywhere
2. **Safety**: No crashes during error formatting
3. **Context**: Automatic context capture
4. **Reusability**: Engineers copy the pattern
5. **User-Friendly**: Clear separation of internal vs external messages
6. **Maintainable**: Error logic centralized per module

---

## Code Review Checklist

- [ ] Functions use `@with_error_context()` decorator
- [ ] Exception handlers use `error_handler.handle()`
- [ ] No direct `str(e)` calls
- [ ] CLI commands follow standard pattern
- [ ] User messages don't expose Python internals
- [ ] Context includes relevant parameters

---

## Anti-Patterns to Avoid

### ❌ Don't: Use str(e) directly
```python
# BAD
except Exception as e:
    print(f"Error: {str(e)}")  # Can crash!
```

### ❌ Don't: Show Python internals to users
```python
# BAD
except Exception as e:
    click.echo(traceback.format_exc())  # Users see stack trace
```

### ❌ Don't: Lose context
```python
# BAD
except Exception as e:
    raise ValueError("Something went wrong")  # Lost original error
```

### ✅ Do: Use the pattern
```python
# GOOD
except Exception as e:
    message = error_handler.handle(e)
    raise UserFriendlyError(message) from e
```

---

## Related Patterns

- **Existing**: `ProcessorErrorHandlerMixin` in `_internal/utils/error_handling.py`
- **Existing**: `ErrorHandler` in `cli/utils/error_handler.py`
- **Standard**: Python's logging context pattern
- **Industry**: Click's exception handling recommendations

---

## References

- Internal: `agent_actions/_internal/utils/error_handling.py` - Existing error mixin
- Internal: `agent_actions/cli/utils/error_handler.py` - Existing CLI handler
- Pattern: Decorator Pattern for cross-cutting concerns
- Pattern: Template Method for customizable handlers
- Principle: Single Responsibility - one handler per module