# Contributing to Agent Actions

Thank you for contributing to Agent Actions! This guide covers coding standards and development workflow.

## Development Setup

```bash
# Install dependencies
task dev

# Install pre-commit hooks
task hooks:install
```

## Running Quality Checks

```bash
# Run all checks
task check

# Individual checks
task lint          # pylint
task lint:ruff     # ruff (logging rules)
task lint:logging  # AST-based logging checker
task mypy          # type checking

# Run pre-commit on all files
task hooks:run
```

## Logging Guidelines

This project uses **f-strings** as the standard logging format for readability and consistency.

### Correct Patterns

```python
# F-strings (project standard)
logger.info(f"Processing {item_id} with value {value}")
logger.debug(f"Workflow {name} completed in {duration:.2f} seconds")
logger.warning(f"Retry attempt {attempt}/{max_retries} for {operation}")
logger.error(f"Failed to process {item_id}: {error}")

# In exception handlers, use .exception() for automatic traceback
try:
    do_something()
except Exception as e:
    logger.exception(f"Unexpected error processing {item}")  # Preferred
    # NOT: logger.error(f"Error: {e}", exc_info=True)
```

### Incorrect Patterns

```python
# BAD: Missing f-prefix with {variable} syntax
# This logs literal "{item_id}" instead of the value!
logger.info("Processing {item_id}")

# BAD: Mixed formatting styles
logger.info("Processing {item_id} with %s", value)

# BAD: Using .error() with exc_info=True in exception handlers
# Use .exception() instead
logger.error(f"Error: {e}", exc_info=True)
```

### Why This Matters

The bug pattern `logger.info("Processing {item_id}")` (missing `f` prefix) is particularly dangerous because:

1. **No exception raised** - Code runs without errors
2. **Silent failure** - Logs show `{item_id}` literally instead of the value
3. **Hard to detect** - Only visible when you read the logs carefully
4. **Wastes debugging time** - Logs are useless for troubleshooting

### Automated Detection

We use multiple tools to catch logging issues:

1. **Ruff** (`task lint:ruff`) - Catches logging anti-patterns
2. **AST Checker** (`task lint:logging`) - Detects `{var}` without f-prefix
3. **Pre-commit hooks** - Runs both on every commit

## Testing

```bash
# Run all tests
task test

# Run with coverage
task test:coverage

# Run specific test types
task test:unit
task test:integration

# Run in parallel
task test:fast
```

## Code Style

- Python 3.11+
- 4-space indentation
- 100 character line length
- Type hints encouraged
- Run `task check` before committing

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes
3. Ensure `task check` passes
4. Ensure `task test` passes
5. Submit PR with clear description
