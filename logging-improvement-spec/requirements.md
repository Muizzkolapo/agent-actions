# Logging Iteration 2: File-Based Logging Requirements

## Overview

Based on analysis of dbt's logging approach, we need to enhance our logging infrastructure to write to dedicated log files instead of primarily to console/UI. This iteration focuses on making logs persistent, structured, and scannable like professional tools (dbt, pytest, etc.).

## Current State

**What we have:**
- ✅ Structured logging with correlation IDs
- ✅ Context injection (agent_name, workflow, etc.)
- ✅ Credential redaction
- ✅ HumanFormatter and JSONFormatter
- ✅ Console output with colors

**Current problem:**
- ❌ Logs go to console/UI instead of persistent files
- ❌ No `logs/agent_actions.log` file like dbt has `logs/dbt.log`
- ❌ Hard to review execution history after the fact
- ❌ No log rotation or retention policy
- ❌ Can't easily grep/analyze past runs

## Goals

1. **Persistent Logging**: Write all logs to `logs/agent_actions.log` by default
2. **Session Separation**: Clear visual boundaries between workflow runs (like dbt's `======`)
3. **Dual Output**: Console for real-time feedback + file for historical analysis
4. **Log Management**: Rotation, retention, and cleanup policies
5. **Compatibility**: Don't break existing console output behavior

## Requirements

### 1. File Handler Configuration (P0)

**REQ-1.1: Default File Handler**
- MUST write logs to `logs/agent_actions.log` by default
- MUST create `logs/` directory if it doesn't exist
- MUST use project root as base directory for log files
- SHOULD support configurable log directory via environment variable `AGENT_ACTIONS_LOG_DIR`

**REQ-1.2: Log Rotation**
- MUST rotate logs when file reaches 10MB by default
- MUST keep last 5 backup files (agent_actions.log.1, .2, etc.)
- SHOULD support configurable rotation size and backup count
- File handler should use `RotatingFileHandler` (already imported)

**REQ-1.3: File Format**
- MUST use structured format in log file (timestamp, level, correlation_id, agent_name, message)
- SHOULD use human-readable format by default (not JSON) for easy scanning
- MAY support JSON format for programmatic analysis via config

### 2. Session Separation (P0)

**REQ-2.1: Workflow Boundaries**
- MUST write visual separator at start of each workflow
- Separator format: `============================== TIMESTAMP | CORRELATION_ID ==============================`
- MUST include timestamp and correlation_id in separator
- Example: `============================== 09:49:19.633 | fba9c519 ==============================`

**REQ-2.2: Workflow Summary**
- MUST log workflow metadata at start (agent count, mode, project)
- MUST log workflow summary at end (duration, status, agents executed)
- SHOULD include environment info (Python version, OS) once per session

### 3. Dual Output Strategy (P0)

**REQ-3.1: Console Handler**
- MUST keep existing console output for real-time user feedback
- Console should show INFO and above by default
- Console should use colored HumanFormatter (existing)

**REQ-3.2: File Handler**
- File should capture DEBUG and above by default
- File should use detailed format with full context
- File should NOT use colors (plain text)

**REQ-3.3: Handler Independence**
- Console and file handlers must have independent log levels
- File can be more verbose (DEBUG) while console stays clean (INFO)
- Both handlers share same filters (credential redaction, context injection)

### 4. Log File Location (P1)

**REQ-4.1: Project-Relative Paths**
- Log file MUST be relative to project root by default
- If in a project directory: `<project_root>/logs/agent_actions.log`
- If outside project: `~/.agent-actions/logs/agent_actions.log` (fallback)

**REQ-4.2: Environment Override**
- `AGENT_ACTIONS_LOG_DIR` env var can override log directory
- `AGENT_ACTIONS_LOG_FILE` env var can override log filename
- Both absolute and relative paths should be supported

### 5. Configuration Integration (P1)

**REQ-5.1: YAML Configuration**
- Support log file settings in `project.yaml`:
  ```yaml
  logging:
    log_level: INFO
    log_file:
      enabled: true
      path: logs/agent_actions.log
      max_bytes: 10485760  # 10MB
      backup_count: 5
      level: DEBUG
    console:
      enabled: true
      level: INFO
      format: human
  ```

**REQ-5.2: CLI Overrides**
- `--log-file <path>` flag to specify custom log file location
- `--no-log-file` flag to disable file logging
- Existing `--debug` flag should set BOTH console and file to DEBUG

### 6. Backward Compatibility (P0)

**REQ-6.1: No Breaking Changes**
- Existing console behavior must remain unchanged by default
- All existing log calls should work without modification
- Existing tests should pass without changes

**REQ-6.2: Graceful Degradation**
- If log directory can't be created, log error but continue execution
- If file handler fails, fall back to console-only logging
- Never crash the application due to logging configuration issues

### 7. Performance Considerations (P2)

**REQ-7.1: Async Logging**
- Consider `QueueHandler` for async file writes in high-throughput scenarios
- File I/O should not block agent execution
- May defer to future iteration if not critical

**REQ-7.2: Buffering**
- File handler should use buffered I/O
- Flush on ERROR level or higher
- Flush on workflow completion

## Non-Requirements (Out of Scope)

- ❌ Remote logging (syslog, cloud services) - future iteration
- ❌ Structured log parsing tools - users can use existing tools
- ❌ Log compression - defer to external tools
- ❌ Real-time log tailing UI - users can use `tail -f`
- ❌ Multi-process log aggregation - single process assumed

## Success Criteria

1. **After running `agent-actions run -a my_agent`:**
   - ✅ File `logs/agent_actions.log` exists in project directory
   - ✅ File contains full DEBUG logs with correlation IDs
   - ✅ Console shows clean INFO-level output (existing behavior)
   - ✅ Session separator visible in log file

2. **After 10 workflow runs:**
   - ✅ Log file has 10 session separators
   - ✅ All correlation IDs are unique
   - ✅ Can grep for specific correlation ID to see full workflow trace

3. **After log file exceeds 10MB:**
   - ✅ Rotation occurs automatically
   - ✅ Backup files created (agent_actions.log.1, etc.)
   - ✅ No data loss during rotation

4. **Configuration flexibility:**
   - ✅ Can disable file logging with `--no-log-file`
   - ✅ Can set custom path with `--log-file custom.log`
   - ✅ Can configure via `project.yaml` logging section

## Comparison to DBT

| Feature | DBT | Our Target |
|---------|-----|------------|
| Log file location | `logs/dbt.log` | `logs/agent_actions.log` |
| Session separator | `======` with timestamp + UUID | `======` with timestamp + correlation_id |
| Dual output | Console + file | Console + file |
| Log rotation | ✅ | ✅ |
| Structured format | Human-readable | Human-readable (JSON optional) |
| Environment vars | ❌ | ✅ `AGENT_ACTIONS_LOG_DIR` |
| Configuration file | `dbt_project.yml` | `project.yaml` |

---

# Logging Iteration 3: Developer Mode Requirements

## Overview

As an AI engineer developing the agent-actions tool, there are times when full verbose debugging output is needed, and times when clean user-facing output is preferred. This iteration adds a developer/debug mode that provides three distinct levels of logging output.

## User Story

> "As an AI engineer when I am developing the agent-actions tool, sometimes I want full verbose and sometimes I don't"

## Current State (Post-Iteration 2)

**What we have:**
- ✅ File-based logging to `logs/agent_actions.log`
- ✅ Dual output (console + file)
- ✅ Structured logging with correlation IDs
- ✅ Credential redaction

**Current problem:**
- ❌ Console shows file references like `(prompt_preparation_service.py:222)` in normal mode
- ❌ File logs also show source location in normal mode (should only be in dev mode)
- ❌ No way to toggle between clean user output vs developer debugging output
- ❌ Log verbosity is all-or-nothing (DEBUG vs INFO)

## Goals

1. **Clean User Output**: Console shows clean, dbt-style output without file references by default
2. **Developer Mode**: Enable detailed debugging output with source file/line references when needed
3. **Three-Tier System**: Normal (clean), Verbose (more detail), Debug (full developer mode)
4. **Flexible Control**: Toggle via CLI flags or environment variables

## Requirements

### 1. Source Location Control (P0)

**REQ-1.1: Default Console Output (Normal Mode)**
- MUST NOT show source file/line references in console output
- Console format: `10:30:45.123 INFO [abc-123] [my-agent] Processing complete`
- NO format: `10:30:45.123 INFO [abc-123] [my-agent] Processing complete (task.py:42)`
- MUST use `HumanFormatter(use_colors=True, include_source_location=False)` for console

**REQ-1.2: Default File Output (Normal Mode)**
- MUST NOT show source file/line references in file output by default
- File format: `10:30:45.123 INFO [abc-123] [my-agent] Processing complete`
- File should be readable by users for troubleshooting their workflows
- Only developer mode should add source location to files

**REQ-1.3: Developer Mode Console Output**
- MUST show source file/line references when `--debug` flag is used
- Console format: `10:30:45.123 DEBUG [abc-123] [my-agent] Processing complete (task.py:42)`
- Helps developers debug the agent-actions codebase itself

**REQ-1.4: Developer Mode File Output**
- MUST show source file/line references in file when `--debug` flag is used
- Same format as console but without colors
- Useful for reviewing detailed traces after debugging session

### 2. Three-Tier Output System (P0)

**REQ-2.1: Normal Mode (Default)**
- CLI output: INFO level, no source location, clean user-facing messages
- File output: DEBUG level, no source location, operational details for users
- Example: `agent-actions run -a my_agent`

**REQ-2.2: Verbose Mode**
- CLI output: INFO level, no source location, more detailed user messages
- File output: DEBUG level, no source location, full operational details
- Example: `agent-actions run -a my_agent -v` or `agent-actions run -a my_agent --verbose`
- Note: In current implementation, verbose and normal are the same level

**REQ-2.3: Debug/Developer Mode**
- CLI output: DEBUG level, WITH source location, internal mechanics visible
- File output: DEBUG level, WITH source location, full debugging context
- Example: `agent-actions run -a my_agent --debug`
- Intended for developers working on agent-actions itself

### 3. Configuration Control (P0)

**REQ-3.1: CLI Flags**
- MUST support `--debug` flag to enable developer mode
- SHOULD support `-v` or `--verbose` flag for verbose user output
- Both flags should be global (work with all commands)
- `--debug` takes precedence over `-v` if both specified

**REQ-3.2: Environment Variables**
- MUST support `AGENT_ACTIONS_DEBUG=1` to enable developer mode globally
- SHOULD be convenient shortcut that sets multiple internal flags:
  - `include_source_location=True`
  - `log_level=DEBUG`
  - `file_log_level=DEBUG`
- Example: `AGENT_ACTIONS_DEBUG=1 agent-actions run -a my_agent`

**REQ-3.3: LoggingConfig Integration**
- `include_source_location` field MUST default to `False` (changed from current `True`)
- When debug mode enabled, set to `True`
- Console handler ALWAYS uses `include_source_location=False` unless debug mode
- File handler uses config value (False by default, True in debug mode)

### 4. Implementation Details (P1)

**REQ-4.1: HumanFormatter Source Location Logic**
```python
# In HumanFormatter.format()
if self.include_source_location:
    location = f'{record.filename}:{record.lineno}'
    formatted = f'{formatted} {self.DIM}({location}){self.RESET}'
```
- This logic already exists
- Just need to control when `include_source_location=True`

**REQ-4.2: Console Handler Configuration**
```python
# Normal mode (default)
console_formatter = HumanFormatter(
    use_colors=True,
    include_source_location=False  # ALWAYS False unless debug mode
)

# Debug mode
console_formatter = HumanFormatter(
    use_colors=True,
    include_source_location=True  # Show file:line for debugging
)
```

**REQ-4.3: File Handler Configuration**
```python
# Normal mode (default)
file_formatter = HumanFormatter(
    use_colors=False,
    include_source_location=False  # False by default
)

# Debug mode
file_formatter = HumanFormatter(
    use_colors=False,
    include_source_location=True  # Show file:line for debugging
)
```

### 5. CLI Integration (P1)

**REQ-5.1: Update main.py Debug Flag Handling**
```python
# Current (lines 96-105 in main.py)
debug_mode = '--debug' in argv
verbose_mode = '--verbose' in argv or '-v' in argv

if debug_mode:
    level = 'DEBUG'
    include_source = True  # NEW
elif verbose_mode:
    level = 'INFO'
    include_source = False  # NEW
else:
    level = 'INFO'
    include_source = False  # NEW
```

**REQ-5.2: Pass to LoggerFactory**
```python
# In main.py initialization
config = LoggingConfig.from_environment()
config.default_level = level
config.include_source_location = include_source  # NEW
LoggerFactory.initialize(config)
```

### 6. Documentation (P1)

**REQ-6.1: Developer Logging Guide**
- Create `dev_artefacts/DEVELOPER_LOGGING_GUIDE.md`
- Document all three modes (Normal, Verbose, Debug)
- Show example output for each mode
- Explain when to use each mode

**REQ-6.2: CLI Help Text**
```bash
agent-actions [command] [options]

Global Options:
  --debug         Enable debug mode with source file/line references (for developers)
  -v, --verbose   Enable verbose output with more detail (for users)
  (default)       Clean output without technical details
```

**REQ-6.3: Environment Variable Documentation**
```markdown
| Variable | Values | Default | Purpose |
|----------|--------|---------|---------|
| AGENT_ACTIONS_DEBUG | 1 | (empty) | Enable developer mode globally |
| AGENT_ACTIONS_LOG_LEVEL | DEBUG,INFO,WARNING,ERROR | INFO | Console log level |
| AGENT_ACTIONS_FILE_LOG_LEVEL | DEBUG,INFO,WARNING,ERROR | DEBUG | File log level |
```

### 7. Backward Compatibility (P0)

**REQ-7.1: No Breaking Changes**
- Existing `--debug` flag behavior preserved (sets level to DEBUG)
- Adds source location display as additional feature
- All existing tests should pass

**REQ-7.2: Default Behavior Change**
- Current: `include_source_location=True` by default
- New: `include_source_location=False` by default
- Justification: Cleaner user output, matches dbt/pytest patterns

### 8. Testing Requirements (P1)

**REQ-8.1: Test Normal Mode**
- Console output does NOT contain `(file.py:123)` patterns
- File output does NOT contain `(file.py:123)` patterns
- Log messages still have timestamp, level, correlation_id, message

**REQ-8.2: Test Debug Mode**
- Console output DOES contain `(file.py:123)` patterns
- File output DOES contain `(file.py:123)` patterns
- All debug-level logs visible

**REQ-8.3: Test Mode Switching**
- Can switch from normal to debug and back
- Environment variable overrides work
- CLI flag takes precedence over environment

## Success Criteria

1. **Default Behavior (Normal Mode):**
   ```bash
   $ agent-actions run -a my_agent
   10:30:45 INFO Starting agent-actions CLI
   10:30:46 INFO [abc-123] Starting agent workflow
   10:30:50 INFO [abc-123] [my-agent] Processing complete
   ```
   - ✅ No file references visible
   - ✅ Clean, dbt-style output
   - ✅ File logs have same format (no source location)

2. **Debug Mode:**
   ```bash
   $ agent-actions run -a my_agent --debug
   10:30:45.123 DEBUG Starting agent-actions CLI (main.py:140)
   10:30:46.456 DEBUG [abc-123] Starting agent workflow (agent_workflow.py:85)
   10:30:46.789 DEBUG [abc-123] Loading configuration (config_loader.py:42)
   10:30:50.012 INFO [abc-123] [my-agent] Processing complete (task.py:215)
   ```
   - ✅ File references visible `(file.py:line)`
   - ✅ DEBUG level logs shown
   - ✅ Useful for debugging agent-actions codebase

3. **Environment Variable:**
   ```bash
   $ export AGENT_ACTIONS_DEBUG=1
   $ agent-actions run -a my_agent
   # Same output as --debug flag
   ```
   - ✅ Environment variable works
   - ✅ Convenient for multiple commands

4. **Log Files:**
   - Normal mode: `logs/agent_actions.log` has no source location
   - Debug mode: `logs/agent_actions.log` has source location
   - Both modes: Full DEBUG-level detail in file

## Output Comparison

### Normal Mode (Clean)
```
10:30:45 INFO Starting agent-actions CLI
10:30:46 INFO [abc-123] Starting agent workflow
10:30:46 INFO [abc-123] Found 2 agents to run
10:30:47 INFO [abc-123] [fact_extractor] Starting agent execution
10:30:50 INFO [abc-123] [fact_extractor] Agent batch submitted
10:30:50 INFO [abc-123] Workflow completed (duration=4.32s)
```

### Debug Mode (Developer)
```
10:30:45.123 DEBUG Starting agent-actions CLI (main.py:140)
10:30:45.234 DEBUG Initializing logging system (factory.py:48)
10:30:45.345 DEBUG Logging to file: /path/to/logs/agent_actions.log (factory.py:283)
10:30:46.456 DEBUG [abc-123] Starting agent workflow (agent_workflow.py:85)
10:30:46.567 DEBUG [abc-123] Found 2 agents to run (agent_workflow.py:120)
10:30:46.678 DEBUG [abc-123] Loading configuration from /path/to/config (config_loader.py:42)
10:30:47.789 INFO [abc-123] [fact_extractor] Starting agent execution (batch_service.py:156)
10:30:47.890 DEBUG [abc-123] [fact_extractor] Preparing prompt (prompt_preparation_service.py:222)
10:30:50.001 INFO [abc-123] [fact_extractor] Agent batch submitted (batch_service.py:180)
10:30:50.112 INFO [abc-123] Workflow completed (duration=4.32s) (agent_workflow.py:250)
```

## References

- Iteration 2 requirements: `logging-improvement-spec/requirements.md` (lines 1-190)
- Existing implementation: `agent_actions/logging/factory.py`
- CLI implementation: `agent_actions/cli/main.py` (lines 96-105)
- Research findings: Best practices from dbt, pytest, ruff
