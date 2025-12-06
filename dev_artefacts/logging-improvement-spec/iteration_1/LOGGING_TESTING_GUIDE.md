# Manual Testing Guide for Logging Infrastructure

This guide provides comprehensive manual tests to validate the logging improvements implemented in PR #553.

## Overview

The logging infrastructure adds:
- Structured logging with correlation context
- Credential redaction for security
- Enhanced error messages with suggestions
- Performance metrics and timing
- Batch processing observability
- Exception handling improvements

---

## 1. Basic Logging Output Tests

**Test different log levels:**
```bash
# Default INFO level
agent-actions run -a your_agent

# Debug level (verbose output)
agent-actions run -a your_agent --debug

# Set via environment variable
AGENT_ACTIONS_LOG_LEVEL=DEBUG agent-actions run -a your_agent
```

**Expected Results:**
- INFO: Should see agent start/completion messages with durations
- DEBUG: Should see detailed execution steps, file operations, API calls
- No CRITICAL-only silence like before

---

## 2. Correlation Context & Workflow Tracking

**Test correlation IDs across agent execution:**
```bash
agent-actions run -a your_agent --debug | grep correlation_id
```

**Expected Results:**
- Every log line should have the same `correlation_id` for a single workflow run
- Agent name and index should appear in logs: `agent_name=your_agent`, `agent_index=1`
- Workflow start/completion logs with total duration

**What to look for:**
```
Starting workflow execution | correlation_id=abc-123 | agent_count=3
Starting agent execution | agent_name=agent1 | agent_index=1 | correlation_id=abc-123
Completed agent execution | agent_name=agent1 | duration=2.5s | correlation_id=abc-123
Workflow completed successfully | duration=7.8s | correlation_id=abc-123
```

---

## 3. Credential Redaction Tests

**Test API key redaction in logs:**

Create a test agent config with an API key, then run with DEBUG level:
```bash
# This will log API configuration at DEBUG level
agent-actions run -a test_agent --debug 2>&1 | grep -i "api_key\|token\|secret"
```

**Expected Results:**
- API keys should appear as `[REDACTED]`
- Patterns like `sk-xxxxx`, `anthropic-xxxxx` should be redacted
- Environment variables in logs should be redacted

**Test extra fields redaction:**
```python
# Add this to any agent code and run with --debug
logger.info("Processing request", extra={
    'api_key': 'sk-real-key-12345',
    'config': {'token': 'secret-token', 'timeout': 30}
})
```
Should log: `api_key=[REDACTED]`, `config={'token': '[REDACTED]', 'timeout': 30}`

---

## 4. Exception Handling & Error Messages

### Test ConfigurationError with suggestions:
```bash
# Try with invalid provider
# Edit an agent config to have: model_vendor: invalid_vendor
agent-actions run -a test_agent
```

**Expected Output:**
```
ConfigurationError: Unknown provider type
  provider_type: invalid_vendor
  supported_providers: ['openai', 'gemini', 'ollama', 'anthropic']
  suggestion: Set model_vendor to one of: openai, gemini, ollama, anthropic. Check your agent configuration.
```

### Test FileLoadError with alternatives:
```bash
# Try loading non-existent config
agent-actions run -a nonexistent_agent
```

**Expected Output:**
```
FileLoadError: Configuration file not found
  file_path: /path/to/nonexistent_agent.yml
  alternatives_checked: [/alt/path1, /alt/path2, /alt/path3]
  found_alternatives: /alt/path2/similar.yml (if any exist)
  suggestion: File not found at /path. Check if the file exists or use an absolute path. Found similar file at: ...
```

### Test ValidationError with field details:
```python
# Create agent that calls a loader without file_path or content
# Run and check error message
```

**Expected Output:**
```
ValidationError: Either file_path or content must be provided for tabular processing
  failed_fields: ['file_path', 'content']
  expected: At least one of file_path or content must be provided
  actual_values: {'file_path': None, 'content': None}
  suggestion: Provide either the file_path parameter (path to tabular file) or the content parameter (string content) for tabular data processing.
```

---

## 5. Batch Processing Metrics

**Test batch job metrics:**
```bash
# Run an agent that uses batch processing
agent-actions run -a batch_agent --debug
```

**Expected Results:**
- Batch submission logs: `Submitting batch job | batch_size=50 | vendor=openai | batch_id=batch_xxx`
- Batch status checks: `Checking batch status | batch_id=batch_xxx | status=processing`
- Individual item logs: `Processing batch item | batch_id=batch_xxx | item_id=item_1`
- Completion metrics: `Batch completed | batch_id=batch_xxx | duration=45.2s | items_processed=50 | throughput=1.1 items/s`

---

## 6. Retry Attempt Logging

**Test retry logging:**
```bash
# Run an agent that might fail and retry (e.g., with network issues)
# Or simulate by causing temporary API failures
agent-actions run -a flaky_agent --debug
```

**Expected Results:**
```
Retrying API call | attempt=1 | max_attempts=3 | wait_time=2.0s | reason=Connection timeout
Retrying API call | attempt=2 | max_attempts=3 | wait_time=4.0s | reason=Connection timeout
API call succeeded | attempt=3 | total_wait_time=6.0s
```

---

## 7. JSON vs Human Log Format

**Test JSON format:**
```bash
AGENT_ACTIONS_LOG_FORMAT=json agent-actions run -a your_agent
```

**Expected Output:**
```json
{"timestamp": "2025-01-27T10:30:45.123Z", "level": "INFO", "message": "Starting agent execution", "correlation_id": "abc-123", "agent_name": "your_agent", "agent_index": 1}
```

**Test Human format (default):**
```bash
agent-actions run -a your_agent
```

**Expected Output (colored, readable):**
```
10:30:45.123 INFO [abc-123] [your_agent] Starting agent execution
```

---

## 8. Execution Timing Tests

**Test agent timing logs:**
```bash
agent-actions run -a your_agent --debug
```

**Expected Results:**
```
Starting agent execution | agent_name=agent1 | agent_index=1 | status=starting
Completed agent execution | agent_name=agent1 | agent_index=1 | duration=2.34s | status=success
```

**Test workflow timing:**
```
Starting workflow execution | agent_count=5 | concurrency_limit=5
Workflow completed successfully | duration=12.5s | agents_executed=5 | status=success
```

---

## 9. Parallel Execution Logging

**Test parallel execution with correlation:**
```bash
agent-actions run -a multi_agent --parallel --debug
```

**Expected Results:**
- All logs from parallel agents should have the same `correlation_id`
- Each agent should have unique `agent_name` and `agent_index`
- Logs should be interleaved but identifiable by agent name
- No credential leaks even with concurrent API calls

---

## 10. Silent Exception Handler Verification

**Test that exceptions are no longer silent:**

Try operations that previously failed silently:
- Invalid JSON in source data files
- Missing batch status files
- Network timeouts
- Invalid UDF expressions
- Dangerous patterns in WHERE clauses

**Expected Results:**
- All exceptions should now log with `ERROR` level
- Should include `exc_info=True` with full traceback
- Should include structured context (file_path, operation, etc.)
- Should have helpful suggestions in error messages

---

## 11. Print Statement Migration Verification

**Verify no more diagnostic prints:**
```bash
# Run various commands and check stderr/stdout
agent-actions run -a your_agent 2>&1 | grep -E "^(DEBUG|INFO|WARNING|ERROR)"
```

**Expected Results:**
- No more `print()` output in diagnostic code
- All diagnostic output should be structured logs
- User-facing output (CLI, console.print) still works normally

---

## 12. Module-Level Log Control

**Test per-module log levels:**
```yaml
# Add to your project.yaml or config
logging:
  log_level: INFO
  module_levels:
    agent_actions.llm_invocation: DEBUG
    agent_actions.validation: WARNING
```

```bash
agent-actions run -a your_agent
```

**Expected Results:**
- LLM invocation logs at DEBUG (very verbose)
- Validation logs only at WARNING or above (quiet)
- Other modules at INFO

---

## Quick Smoke Test Script

Run this sequence to quickly verify core functionality:

```bash
# 1. Basic run with default settings
agent-actions run -a simple_agent

# 2. Debug mode
agent-actions run -a simple_agent --debug

# 3. JSON format
AGENT_ACTIONS_LOG_FORMAT=json agent-actions run -a simple_agent

# 4. Verify no credentials leaked
agent-actions run -a api_agent --debug 2>&1 | grep -i "sk-\|api.*key" | grep -v REDACTED
# Should return nothing (all keys redacted)

# 5. Test error message improvements
agent-actions run -a nonexistent_agent 2>&1 | grep -A 5 "suggestion:"

# 6. Check correlation IDs work
agent-actions run -a multi_agent --debug 2>&1 | grep correlation_id | head -5
```

---

## What Success Looks Like

✅ **Logging is visible** - No more CRITICAL-only silence
✅ **Context is tracked** - correlation_id appears in every log
✅ **Credentials are safe** - No API keys visible in logs
✅ **Errors are helpful** - Suggestions point to fixes
✅ **Performance is tracked** - Timing data in completion logs
✅ **No print statements** - All diagnostic output is structured
✅ **Exceptions are logged** - No more silent failures

---

## Test Results Checklist

Use this checklist to track your testing progress:

- [ ] Basic logging output (INFO vs DEBUG)
- [ ] Correlation context tracking
- [ ] Credential redaction (API keys, tokens)
- [ ] ConfigurationError suggestions
- [ ] FileLoadError with alternatives
- [ ] ValidationError with field details
- [ ] Batch processing metrics
- [ ] Retry attempt logging
- [ ] JSON vs Human format
- [ ] Execution timing logs
- [ ] Parallel execution logging
- [ ] Silent exception fixes verified
- [ ] Print statement migration verified
- [ ] Module-level log control

---

## Troubleshooting

### Logs not appearing?
- Check that log level is not set to CRITICAL: `echo $AGENT_ACTIONS_LOG_LEVEL`
- Verify LoggerFactory is initialized (should happen automatically in CLI)

### Credentials still visible in logs?
- Report immediately as a security issue
- Check if using custom logging that bypasses filters

### Error messages lack suggestions?
- Verify you're on the feature/logging-improvements branch
- Check that the specific error type was enhanced (ConfigurationError, FileLoadError, ValidationError)

### Performance degradation?
- Logging overhead should be minimal (<5% in most cases)
- Consider using INFO level instead of DEBUG for production
- Check if file handler is causing I/O bottleneck

---

## Related Files

- **Logging Implementation**: `agent_actions/logging/`
- **Exception Classes**: `agent_actions/shared/exceptions.py`
- **Test Suite**: `tests/test_logging/`
- **Design Doc**: `logging-improvement-spec/design.md`
- **Requirements**: `logging-improvement-spec/requirements.md`
- **Tasks**: `logging-improvement-spec/tasks.md`
