# Developer Logging and Debug Mode Guide

## Overview

agent-actions provides a three-tier logging system that balances clean user-facing output with powerful developer debugging capabilities. This guide explains when and how to use each mode.

## Quick Start

### Enable Debug Mode

**Option 1: CLI Flag** (for single command)
```bash
agent-actions run -a my_agent --debug
```

**Option 2: Environment Variable** (for session)
```bash
export AGENT_ACTIONS_DEBUG=1
agent-actions run -a my_agent
```

### Disable Debug Mode

```bash
# Just run without --debug flag
agent-actions run -a my_agent

# Or unset environment variable
unset AGENT_ACTIONS_DEBUG
```

## Three-Tier Output System

### Normal Mode (Default)

**Use when**: Running workflows in production or as an end user

**Console Output**:
```
10:30:45 INFO Starting agent-actions CLI
10:30:46 INFO [abc-123] Starting agent workflow
10:30:46 INFO [abc-123] Found 2 agents to run
10:30:47 INFO [abc-123] [fact_extractor] Starting agent execution
10:30:50 INFO [abc-123] [fact_extractor] Agent batch submitted
10:30:50 INFO [abc-123] Workflow completed (duration=4.32s)
```

**Characteristics**:
- Clean, dbt-style output
- No source file/line references
- INFO level and above
- Colored for readability
- Focus on workflow progress

**File Output** (`logs/agent_actions.log`):
```
10:30:45.123 DEBUG Initializing logging system
10:30:45.234 INFO Starting agent-actions CLI
10:30:46.456 DEBUG Loading configuration from /path/to/config
10:30:46.567 INFO [abc-123] Starting agent workflow
10:30:47.789 DEBUG [abc-123] [fact_extractor] Preparing prompt
10:30:50.012 INFO [abc-123] Workflow completed (duration=4.32s)
```

**Characteristics**:
- DEBUG level and above (more detail)
- No source file/line references
- No colors (plain text)
- Timestamps with milliseconds
- Useful for troubleshooting workflows

### Verbose Mode

**Use when**: Need more detail but still user-facing

```bash
agent-actions run -a my_agent -v
```

**Currently**: Same as normal mode (both use INFO level)

**Future**: May show additional user-facing details

### Debug Mode (Developer)

**Use when**: Developing or debugging agent-actions itself

**Console Output**:
```
10:30:45.123 DEBUG Starting agent-actions CLI (main.py:140)
10:30:45.234 DEBUG Initializing logging system (factory.py:48)
10:30:45.345 DEBUG Logging to file: /path/to/logs/agent_actions.log (factory.py:283)
10:30:46.456 DEBUG [abc-123] Starting agent workflow (agent_workflow.py:85)
10:30:46.567 DEBUG [abc-123] Found 2 agents to run (agent_workflow.py:120)
10:30:46.678 DEBUG [abc-123] Loading configuration (config_loader.py:42)
10:30:47.789 INFO [abc-123] [fact_extractor] Starting agent execution (batch_service.py:156)
10:30:47.890 DEBUG [abc-123] [fact_extractor] Preparing prompt (prompt_preparation_service.py:222)
10:30:50.012 INFO [abc-123] Workflow completed (duration=4.32s) (agent_workflow.py:250)
```

**Characteristics**:
- DEBUG level (most verbose)
- **WITH source file/line references** `(file.py:123)`
- Colored output
- Timestamps with milliseconds
- Shows internal mechanics

**File Output**: Same as console but without colors

## Environment Variables

| Variable | Values | Default | Purpose |
|----------|--------|---------|---------|
| `AGENT_ACTIONS_DEBUG` | `1` | (empty) | Enable developer mode globally |
| `AGENT_ACTIONS_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` | Console log level (overridden by DEBUG mode) |
| `AGENT_ACTIONS_LOG_FORMAT` | `human`, `json` | `human` | Output format |
| `AGENT_ACTIONS_NO_LOG_FILE` | `1` | (empty) | Disable file logging |
| `AGENT_ACTIONS_LOG_FILE` | `/path/to/log` | (auto) | Custom log file path |
| `AGENT_ACTIONS_FILE_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `DEBUG` | File log level |

### Examples

**Disable file logging** (console only):
```bash
export AGENT_ACTIONS_NO_LOG_FILE=1
agent-actions run -a my_agent
```

**Custom log file location**:
```bash
export AGENT_ACTIONS_LOG_FILE=/var/log/my_project/agent_actions.log
agent-actions run -a my_agent
```

**Debug mode** (shortcut):
```bash
export AGENT_ACTIONS_DEBUG=1
# Equivalent to:
# AGENT_ACTIONS_LOG_LEVEL=DEBUG + source location enabled
```

## When to Use Each Mode

### Normal Mode (Default)

✅ **Use for**:
- Production workflows
- CI/CD pipelines
- End-user execution
- Clean status updates
- When you care about workflow results, not code internals

❌ **Don't use for**:
- Debugging agent-actions code
- Investigating internal errors
- Performance profiling

### Debug Mode

✅ **Use for**:
- Developing agent-actions features
- Debugging agent-actions code
- Investigating framework errors
- Understanding execution flow
- Finding performance bottlenecks
- Seeing which functions are called

❌ **Don't use for**:
- Production workflows (too verbose)
- End-user execution (confusing)
- CI/CD logs (too noisy)

## Troubleshooting

### "I'm not seeing debug logs"

**Check 1**: Environment variable
```bash
echo $AGENT_ACTIONS_DEBUG
# Should output: 1
```

**Check 2**: Use `--debug` flag
```bash
agent-actions run -a my_agent --debug
```

**Check 3**: Check log file
```bash
tail -f logs/agent_actions.log
# File always has DEBUG logs (even without --debug)
```

### "I see file references in normal mode"

This is a bug. Normal mode should NOT show `(file.py:123)` patterns.

**Fix**: Ensure you're on the latest version with developer mode support.

**Workaround**: None needed - this indicates a configuration issue.

### "Debug mode is too verbose"

Debug mode is intentionally verbose for developers.

**Solutions**:
1. Use normal mode: `agent-actions run -a my_agent` (no --debug)
2. Review log file instead of console
3. Use grep to filter: `tail -f logs/agent_actions.log | grep ERROR`

### "I want to see credentials in logs"

**Security**: Credentials are automatically redacted for safety.

Pattern redacted:
- `api_key`, `api-key`, `apikey`
- `secret`
- `token`
- `password`
- `credential`

**This is by design and cannot be disabled.**

## For Library Developers

### Adding Logs to agent-actions Code

```python
from agent_actions.logging import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

# This will show source location in debug mode automatically
logger.debug("Loading configuration")  # (my_module.py:42) in debug mode
logger.info("Processing complete")     # No file ref in normal mode
```

### Testing Logging Output

```python
# In tests, check that source location is NOT present by default
config = LoggingConfig(include_source_location=False)
LoggerFactory.initialize(config)

logger = LoggerFactory.get_logger('test')
# ... test that output has no (file.py:line) patterns
```

## Logging Level Decision Framework

When adding new log statements to agent-actions, use this decision tree:

### When to use INFO level

✅ **User-Facing Milestones** - Operations the user initiated or needs to track:
- Workflow start/completion
- Agent execution start/completion
- Batch job submission/completion
- Major command operations (compile, render, run)
- Critical warnings or decisions

❌ **Not for INFO**:
- Internal validation steps
- Data loading/preparation
- Context building
- Schema/prompt validation details
- Task counting/filtering

### When to use DEBUG level

✅ **Internal Operations** - How the system works internally:
- Validation steps (directory, schema, prompt, file)
- Data loading (seed data, static data)
- Context scope processing
- Prompt preparation details
- Task preparation metrics
- Configuration merging

### ServiceLogger Pattern

When using `ServiceLogger`, explicitly mark user-facing operations:

```python
# User-facing operation (visible in normal mode)
ServiceLogger.log_operation_start(logger, 'render template', user_facing=True)
ServiceLogger.log_operation_success(logger, 'render template', user_facing=True)

# Internal operation (only visible in debug mode)
ServiceLogger.log_operation_start(logger, 'validate file', user_facing=False)
ServiceLogger.log_operation_success(logger, 'validate file', user_facing=False)
```

**Default**: `user_facing=False` - you must explicitly mark operations as user-facing.

### Examples

**Good - INFO**:
```python
logger.info('[abc-123] Workflow started')
logger.info('[abc-123] [my-agent] Agent execution completed')
logger.info('Batch job submitted: batch_id=batch_xyz')
```

**Good - DEBUG**:
```python
logger.debug('Validating configuration schema...')
logger.debug('Loaded 15 seed data records from /path/to/seeds')
logger.debug('Preparing prompt for agent: prompt_length=3517')
```

**Bad - Too much INFO**:
```python
logger.info('Checking directory structure...')  # Use DEBUG
logger.info('Merging static data fields...')    # Use DEBUG
logger.info('Task preparation complete: 3 tasks')  # Use DEBUG
```

## Migration Guide

### Breaking Change (v1.x → v2.x)

**What changed**: `include_source_location` now defaults to `False` (was `True`)

**Impact**: Logs no longer show `(file.py:123)` by default

**Migration**:

**Option 1: Use debug mode** (recommended for development)
```bash
export AGENT_ACTIONS_DEBUG=1
# Or use --debug flag
```

**Option 2: Set in code** (not recommended)
```python
config = LoggingConfig(include_source_location=True)
LoggerFactory.initialize(config)
```

**Why this change?**
- Cleaner user-facing output
- Matches industry standards (dbt, pytest)
- Better UX for end users
- Developers can still enable with --debug

## Best Practices

1. **Default to normal mode** for all production workflows
2. **Use debug mode only when developing** agent-actions itself
3. **Check log files** for detailed troubleshooting (always has DEBUG level)
4. **Use correlation IDs** to trace specific workflow executions
5. **Don't commit AGENT_ACTIONS_DEBUG=1** to environment files
6. **Document debug mode** in your team's runbooks

## Examples

### Debugging a Workflow Failure

```bash
# Run with debug mode
agent-actions run -a problematic_agent --debug

# Check the log file for full context
tail -100 logs/agent_actions.log

# Search for errors
grep ERROR logs/agent_actions.log
```

### Finding Correlation ID

```bash
# Normal mode shows correlation ID in brackets
agent-actions run -a my_agent
# Output: 10:30:46 INFO [abc-123] Starting agent workflow

# Search log file for that correlation ID
grep "abc-123" logs/agent_actions.log
# Shows all logs for that specific workflow run
```

### Continuous Development

```bash
# Set debug mode for your development session
export AGENT_ACTIONS_DEBUG=1

# All commands now use debug mode
agent-actions run -a agent1
agent-actions run -a agent2
agent-actions test

# Disable when done
unset AGENT_ACTIONS_DEBUG
```

## FAQ

**Q: Does debug mode slow down execution?**
A: No. The only difference is formatting (adding `(file.py:line)`). No performance impact.

**Q: Can I have debug mode for console but normal for file?**
A: Not currently. Both console and file use the same `include_source_location` setting.

**Q: What's the difference between --debug and --verbose?**
A: Currently both enable INFO level. `--debug` also enables source location and DEBUG level. `-v/--verbose` may gain additional features in the future.

**Q: Can I use debug mode in production?**
A: Technically yes, but not recommended. The output is very verbose and includes internal implementation details that may confuse end users.

**Q: How do I report a logging bug?**
A: Open an issue at https://github.com/Muizzkolapo/agent-actions/issues with:
- Your command
- Expected vs actual output
- Environment variables (sanitized)
- Log file excerpt (sanitized)

## See Also

- [CHANGELOG.md](../CHANGELOG.md) - Release notes
- [LOGGING_TESTING_GUIDE.md](../logging-improvement-spec/LOGGING_TESTING_GUIDE.md) - Testing guide
- [CLI Reference](../agentaction-docs/docs/cli-reference.md) - CLI commands
