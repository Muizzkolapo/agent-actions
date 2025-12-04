# Logging Iteration 2: File-Based Logging Design

## Overview

This document describes the design for adding persistent file-based logging to agent-actions, inspired by dbt's logging approach. We'll maintain existing console behavior while adding comprehensive file logging for debugging and analysis.

## Architecture

### Current State (Iteration 1)

```
LoggerFactory.initialize()
    ↓
Creates console handler with HumanFormatter
    ↓
Adds ContextInjectingFilter + RedactingFilter
    ↓
Logs go to console/stderr
```

### Target State (Iteration 2)

```
LoggerFactory.initialize()
    ↓
Creates TWO handlers:
    ├─ ConsoleHandler (existing behavior)
    │    ├─ Level: INFO
    │    ├─ Format: HumanFormatter (colored)
    │    └─ Output: stderr
    │
    └─ RotatingFileHandler (NEW)
         ├─ Level: DEBUG
         ├─ Format: HumanFormatter (no colors)
         ├─ Output: logs/agent_actions.log
         ├─ Rotation: 10MB max, 5 backups
         └─ Shared filters: ContextInjecting + Redacting
```

## Component Design

### 1. File Handler Setup

**Location:** `agent_actions/logging/factory.py`

**Changes to `LoggerFactory.initialize()`:**

```python
@classmethod
def initialize(cls, config: Optional[LoggingConfig] = None, force: bool = False) -> None:
    """Initialize logging system with console and file handlers."""
    if cls._initialized and not force:
        return

    cls._config = config or LoggingConfig.from_environment()

    # Get or create root logger
    logger = logging.getLogger(cls._root_logger_name)
    logger.setLevel(logging.DEBUG)  # Capture everything
    logger.handlers.clear()

    # Create shared filters
    context_filter = ContextInjectingFilter()
    redacting_filter = RedactingFilter()

    # 1. Console Handler (existing)
    console_handler = cls._create_console_handler(cls._config)
    console_handler.addFilter(context_filter)
    console_handler.addFilter(redacting_filter)
    logger.addHandler(console_handler)

    # 2. File Handler (NEW)
    if cls._config.file_handler_enabled:  # New config option
        file_handler = cls._create_file_handler(cls._config)
        if file_handler:  # May be None if creation failed
            file_handler.addFilter(context_filter)
            file_handler.addFilter(redacting_filter)
            logger.addHandler(file_handler)

    cls._initialized = True
```

**New method: `_create_file_handler()`**

```python
@classmethod
def _create_file_handler(cls, config: LoggingConfig) -> Optional[RotatingFileHandler]:
    """Create rotating file handler for persistent logs.

    Returns:
        RotatingFileHandler or None if creation fails
    """
    try:
        # Determine log file path
        log_file_path = cls._get_log_file_path(config)

        # Ensure directory exists
        log_dir = log_file_path.parent
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create rotating file handler
        handler = RotatingFileHandler(
            filename=str(log_file_path),
            maxBytes=config.file_max_bytes,  # Default 10MB
            backupCount=config.file_backup_count,  # Default 5
            encoding='utf-8'
        )

        # Set level (DEBUG by default for files)
        handler.setLevel(config.file_log_level)

        # Set formatter (HumanFormatter without colors)
        formatter = HumanFormatter(use_colors=False)
        handler.setFormatter(formatter)

        return handler

    except Exception as e:
        # Log error to stderr but don't crash
        sys.stderr.write(f"WARNING: Failed to create log file handler: {e}\n")
        sys.stderr.write("Continuing with console logging only.\n")
        return None
```

**New method: `_get_log_file_path()`**

```python
@classmethod
def _get_log_file_path(cls, config: LoggingConfig) -> Path:
    """Determine log file path based on config and environment.

    Priority (highest to lowest):
    1. Environment variable AGENT_ACTIONS_LOG_FILE (absolute path)
    2. Config file path (from project.yaml)
    3. Default: logs/agent_actions.log (relative to project root or ~/.agent-actions/)
    """
    # 1. Check environment variable
    env_log_file = os.environ.get('AGENT_ACTIONS_LOG_FILE')
    if env_log_file:
        return Path(env_log_file).expanduser().resolve()

    # 2. Check config
    if config.log_file_path:
        path = Path(config.log_file_path)
        if path.is_absolute():
            return path
        # Relative to project root
        return cls._get_project_root() / path

    # 3. Default location
    log_dir_env = os.environ.get('AGENT_ACTIONS_LOG_DIR')
    if log_dir_env:
        return Path(log_dir_env).expanduser() / 'agent_actions.log'

    # Try project root first
    project_root = cls._get_project_root()
    if project_root:
        return project_root / 'logs' / 'agent_actions.log'

    # Fallback to home directory
    return Path.home() / '.agent-actions' / 'logs' / 'agent_actions.log'

@classmethod
def _get_project_root(cls) -> Optional[Path]:
    """Find project root by looking for project.yaml or .git directory."""
    current = Path.cwd()

    # Walk up directory tree
    for parent in [current] + list(current.parents):
        if (parent / 'project.yaml').exists() or (parent / '.git').exists():
            return parent

    return None
```

### 2. Configuration Updates

**Location:** `agent_actions/logging/config.py`

**Add new fields to `LoggingConfig`:**

```python
@dataclass
class LoggingConfig:
    """Configuration for logging system."""

    # Existing fields
    log_level: str = 'INFO'
    log_format: str = 'human'  # 'human' or 'json'
    module_levels: Dict[str, str] = field(default_factory=dict)

    # NEW: File handler configuration
    file_handler_enabled: bool = True
    log_file_path: Optional[str] = None  # None = use default
    file_log_level: str = 'DEBUG'
    file_max_bytes: int = 10485760  # 10MB
    file_backup_count: int = 5
    file_format: str = 'human'  # 'human' or 'json'

    @classmethod
    def from_environment(cls) -> 'LoggingConfig':
        """Create config from environment variables."""
        config = cls()

        # Existing env vars
        if log_level := os.getenv('AGENT_ACTIONS_LOG_LEVEL'):
            config.log_level = log_level.upper()

        if log_format := os.getenv('AGENT_ACTIONS_LOG_FORMAT'):
            config.log_format = log_format.lower()

        # NEW: File handler env vars
        if os.getenv('AGENT_ACTIONS_NO_LOG_FILE') == '1':
            config.file_handler_enabled = False

        if file_level := os.getenv('AGENT_ACTIONS_FILE_LOG_LEVEL'):
            config.file_log_level = file_level.upper()

        return config
```

### 3. Session Separator

**Location:** `agent_actions/orchestration/agent_workflow.py`

**Enhancement to workflow start logging:**

```python
def run(self) -> Dict[str, Any]:
    """Execute workflow with session boundary logging."""
    from agent_actions.logging.context import CorrelationContext

    # Start correlation context
    correlation_id = CorrelationContext.start_workflow(
        workflow_name=self.config.get('name', 'unknown'),
        agent_count=len(self.agents)
    )

    try:
        # NEW: Log session separator
        logger.info(
            f"\n{'=' * 30} {datetime.now().strftime('%H:%M:%S.%f')[:-3]} | "
            f"{correlation_id[:8]} {'=' * 30}"
        )

        # Log workflow start with metadata
        logger.info(
            "Workflow started",
            extra={
                'agent_count': len(self.agents),
                'concurrency_limit': self.concurrency_limit,
                'python_version': platform.python_version(),
                'os': platform.platform()
            }
        )

        # ... existing workflow execution ...

    finally:
        # Log workflow end
        duration = time.time() - start_time
        logger.info(
            f"Workflow completed | duration={duration:.2f}s | "
            f"status={'success' if not error else 'failed'}"
        )
        CorrelationContext.clear_context()
```

### 4. Formatter Updates

**Location:** `agent_actions/logging/formatters.py`

**Enhancement to `HumanFormatter`:**

```python
class HumanFormatter(logging.Formatter):
    """Human-readable log formatter with optional colors."""

    def __init__(self, use_colors: bool = True):
        """Initialize formatter.

        Args:
            use_colors: Whether to use ANSI color codes (True for console, False for file)
        """
        super().__init__()
        self.use_colors = use_colors

        # Existing color setup...

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for human readability."""
        # Timestamp
        timestamp = self.formatTime(record, datefmt='%H:%M:%S')
        timestamp_ms = f"{timestamp}.{int(record.msecs):03d}"

        # Level with optional color
        level = record.levelname
        if self.use_colors:
            level = self._colorize_level(level)

        # Correlation context
        correlation_id = getattr(record, 'correlation_id', None)
        agent_name = getattr(record, 'agent_name', None)

        context_str = ""
        if correlation_id:
            # Show short version (first 8 chars)
            context_str += f"[{correlation_id[:8]}] "
        if agent_name:
            context_str += f"[{agent_name}] "

        # Build message
        message = f"{timestamp_ms} {level:8s} {context_str}{record.getMessage()}"

        # Add exception info if present
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"

        return message
```

## Data Flow

### Log Message Journey

```
Application Code
    │
    ├─ logger.info("Message", extra={...})
    │
    ↓
Logger (agent_actions)
    │
    ├─ Level filter (DEBUG+)
    │
    ├─ ContextInjectingFilter
    │   └─ Adds: correlation_id, agent_name, workflow_name, agent_index
    │
    ├─ RedactingFilter
    │   └─ Redacts: API keys, tokens, passwords in message and extra fields
    │
    ↓
Handler Level Filter
    │
    ├─────────────┬─────────────┐
    │             │             │
    ↓             ↓             ↓
ConsoleHandler  FileHandler  (Future: RemoteHandler)
Level: INFO     Level: DEBUG
    │             │
    ↓             ↓
HumanFormatter  HumanFormatter
(colors=True)   (colors=False)
    │             │
    ↓             ↓
stderr          logs/agent_actions.log
```

### File Structure

```
project_root/
├── logs/
│   ├── agent_actions.log       # Current log file
│   ├── agent_actions.log.1     # Previous rotation
│   ├── agent_actions.log.2     # 2nd previous
│   ├── agent_actions.log.3     # 3rd previous
│   ├── agent_actions.log.4     # 4th previous
│   └── agent_actions.log.5     # 5th previous (oldest)
├── project.yaml
└── agent_workflow/
```

### Log File Content Example

```
============================== 09:49:19.633 | fba9c519 ==============================
09:49:19.633 INFO     [fba9c519] Workflow started
09:49:19.634 INFO     [fba9c519] Found 2 agents to run
09:49:19.634 INFO     [fba9c519] [fact_extractor] Starting agent execution
09:49:19.635 DEBUG    [fba9c519] [fact_extractor] Loading configuration from /path/to/config
09:49:19.640 DEBUG    [fba9c519] [fact_extractor] Preparing prompt for agent 'fact_extractor' in batch mode
09:49:19.650 ERROR    [fba9c519] [fact_extractor] Failed to prepare task for row: Error resolving {seed.exam_syllabus}
Traceback (most recent call last):
  File "prompt_utils.py", line 148, in replace_field_references
    ...
09:49:20.100 INFO     [fba9c519] [fact_extractor] Agent batch submitted
09:49:20.101 INFO     [fba9c519] Workflow completed | duration=0.47s | status=success
============================== 09:50:15.123 | a3b2c1d4 ==============================
09:50:15.123 INFO     [a3b2c1d4] Workflow started
...
```

## Configuration Examples

### Via project.yaml

```yaml
# project.yaml
logging:
  log_level: INFO

  # Console output
  console:
    enabled: true
    level: INFO
    format: human
    colors: true

  # File output (NEW)
  file:
    enabled: true
    path: logs/agent_actions.log  # Relative to project root
    level: DEBUG
    format: human
    max_bytes: 10485760  # 10MB
    backup_count: 5
```

### Via Environment Variables

```bash
# Disable file logging
export AGENT_ACTIONS_NO_LOG_FILE=1

# Custom log file location
export AGENT_ACTIONS_LOG_FILE=/var/log/agent_actions/my_project.log

# Custom log directory (uses agent_actions.log filename)
export AGENT_ACTIONS_LOG_DIR=/var/log/agent_actions

# File log level
export AGENT_ACTIONS_FILE_LOG_LEVEL=DEBUG
```

### Via CLI Flags

```bash
# Custom log file
agent-actions run -a my_agent --log-file custom.log

# Disable file logging
agent-actions run -a my_agent --no-log-file

# Debug mode (sets both console and file to DEBUG)
agent-actions run -a my_agent --debug
```

## Error Handling

### File Handler Creation Failures

```python
def _create_file_handler(cls, config):
    try:
        # ... handler creation ...
        return handler
    except PermissionError as e:
        sys.stderr.write(
            f"WARNING: No permission to write to {log_file_path}. "
            f"Continuing with console logging only.\n"
        )
        return None
    except OSError as e:
        sys.stderr.write(
            f"WARNING: Failed to create log file {log_file_path}: {e}. "
            f"Continuing with console logging only.\n"
        )
        return None
```

**Behavior:**
- Log creation failures print to stderr
- Application continues with console-only logging
- No crash or exception propagation
- User sees warning but workflow proceeds

## Performance Considerations

### Buffering Strategy

```python
# File handler uses buffered I/O by default
handler = RotatingFileHandler(filename=path, ...)

# Flush on high-priority logs
class FlushOnErrorFilter(logging.Filter):
    """Flush file handler on ERROR or CRITICAL."""

    def filter(self, record):
        if record.levelno >= logging.ERROR:
            # Flush all handlers
            for handler in logging.getLogger('agent_actions').handlers:
                if hasattr(handler, 'flush'):
                    handler.flush()
        return True
```

### Rotation Performance

- Rotation happens automatically when file exceeds max_bytes
- Rotation is atomic (no log loss)
- Old logs are renamed (.1 → .2 → .3, etc.)
- Oldest log (.5) is deleted
- Negligible performance impact (< 1ms)

## Testing Strategy

### Unit Tests

```python
def test_file_handler_creation():
    """Test file handler is created and configured correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = LoggingConfig(log_file_path=f"{tmpdir}/test.log")
        LoggerFactory.initialize(config, force=True)

        logger = LoggerFactory.get_logger('test')
        logger.info("Test message")

        # Verify file exists
        log_file = Path(tmpdir) / "test.log"
        assert log_file.exists()

        # Verify content
        content = log_file.read_text()
        assert "Test message" in content
        assert "INFO" in content

def test_log_rotation():
    """Test log rotation when file exceeds max size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = LoggingConfig(
            log_file_path=f"{tmpdir}/test.log",
            file_max_bytes=1024,  # 1KB
            file_backup_count=2
        )
        LoggerFactory.initialize(config, force=True)

        logger = LoggerFactory.get_logger('test')

        # Write enough to trigger rotation
        for i in range(100):
            logger.info("X" * 100)

        # Verify rotation occurred
        assert (Path(tmpdir) / "test.log").exists()
        assert (Path(tmpdir) / "test.log.1").exists()

def test_session_separator():
    """Test workflow start logs session separator."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = LoggingConfig(log_file_path=f"{tmpdir}/test.log")
        LoggerFactory.initialize(config, force=True)

        # Start workflow
        workflow = AgentWorkflow(config={...})
        workflow.run()

        # Verify separator in log file
        content = (Path(tmpdir) / "test.log").read_text()
        assert "==============================" in content
        assert "|" in content  # Has correlation ID
```

### Integration Tests

```python
def test_dual_output():
    """Test both console and file get logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = LoggingConfig(log_file_path=f"{tmpdir}/test.log")
        LoggerFactory.initialize(config, force=True)

        # Capture console output
        import io
        console_capture = io.StringIO()
        console_handler = logging.StreamHandler(console_capture)

        logger = LoggerFactory.get_logger('test')
        logger.info("Dual output test")

        # Both should have the message
        file_content = (Path(tmpdir) / "test.log").read_text()
        console_content = console_capture.getvalue()

        assert "Dual output test" in file_content
        # Note: Console might not have it if level filtering differs
```

## Migration Path

### Phase 1: Add File Handler (This Iteration)
- Add file handler creation
- Keep existing console behavior
- Default: file enabled
- No breaking changes

### Phase 2: Configuration Enhancement (Future)
- Add full YAML configuration support
- Add CLI flags (--log-file, --no-log-file)
- Enhanced error messages

### Phase 3: Advanced Features (Future)
- Async logging with QueueHandler
- Structured log analysis tools
- Log aggregation for multi-process

## References

- Example: `logging-improvement-spec/logs/dbt.log`
- Python RotatingFileHandler: https://docs.python.org/3/library/logging.handlers.html#rotatingfilehandler
- Existing implementation: `agent_actions/logging/factory.py`

---

# Logging Iteration 3: Developer Mode Design

## Overview

This iteration adds developer/debug mode to provide three distinct levels of logging output: Normal (clean user output), Verbose (detailed user output), and Debug (developer mode with source file references).

## Architecture

### Current State (Post-Iteration 2)

```
LoggerFactory.initialize()
    ↓
Creates TWO handlers:
    ├─ ConsoleHandler
    │    ├─ Level: INFO
    │    ├─ Format: HumanFormatter (colored, include_source_location=True)
    │    └─ Output: stderr
    │
    └─ RotatingFileHandler
         ├─ Level: DEBUG
         ├─ Format: HumanFormatter (no colors, include_source_location=True)
         └─ Output: logs/agent_actions.log
```

**Problem**: Both console and file show source location `(file.py:123)` by default

### Target State (Iteration 3)

```
LoggerFactory.initialize(config)
    ↓
Checks debug mode from config.include_source_location
    ↓
Creates TWO handlers with conditional source location:

Normal Mode (default):
    ├─ ConsoleHandler
    │    ├─ Level: INFO
    │    ├─ Format: HumanFormatter (colored, include_source_location=False)
    │    └─ Output: stderr (CLEAN - no file refs)
    │
    └─ RotatingFileHandler
         ├─ Level: DEBUG
         ├─ Format: HumanFormatter (no colors, include_source_location=False)
         └─ Output: logs/agent_actions.log (CLEAN - no file refs)

Debug Mode (--debug flag or AGENT_ACTIONS_DEBUG=1):
    ├─ ConsoleHandler
    │    ├─ Level: DEBUG
    │    ├─ Format: HumanFormatter (colored, include_source_location=True)
    │    └─ Output: stderr (WITH file refs for debugging)
    │
    └─ RotatingFileHandler
         ├─ Level: DEBUG
         ├─ Format: HumanFormatter (no colors, include_source_location=True)
         └─ Output: logs/agent_actions.log (WITH file refs for debugging)
```

## Component Design

### 1. LoggingConfig Changes

**Location:** `agent_actions/logging/config.py`

**Change default value:**

```python
@dataclass
class LoggingConfig:
    """Central logging configuration."""

    default_level: LogLevel = 'INFO'
    handlers: List[HandlerConfig] = field(default_factory=list)
    module_levels: Dict[str, LogLevel] = field(default_factory=dict)
    include_timestamps: bool = True
    include_source_location: bool = False  # CHANGED: was True, now False
    redact_patterns: List[str] = field(
        default_factory=lambda: [
            r'api[_-]?key',
            r'secret',
            r'token',
            r'password',
            r'credential',
        ]
    )
    # ... rest of fields
```

**Add AGENT_ACTIONS_DEBUG environment variable support:**

```python
@classmethod
def from_environment(cls) -> LoggingConfig:
    """Create LoggingConfig from environment variables."""
    level = os.environ.get('AGENT_ACTIONS_LOG_LEVEL', 'INFO').upper()
    if level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
        level = 'INFO'

    log_format = os.environ.get('AGENT_ACTIONS_LOG_FORMAT', 'human').lower()
    if log_format not in ('human', 'json'):
        log_format = 'human'

    # NEW: Check for debug mode
    debug_mode = os.environ.get('AGENT_ACTIONS_DEBUG', '0') == '1'
    if debug_mode:
        level = 'DEBUG'
        include_source = True
    else:
        include_source = False

    handlers = [
        HandlerConfig(
            type='console',
            level=level,
            format=log_format,
        )
    ]

    # File handler configuration from environment
    file_handler_enabled = os.environ.get('AGENT_ACTIONS_NO_LOG_FILE', '0') != '1'
    # ... rest of file handler config

    return cls(
        default_level=level,
        handlers=handlers,
        include_source_location=include_source,  # NEW
        file_handler_enabled=file_handler_enabled,
        log_file_path=log_file_path,
        file_log_level=file_log_level,
    )
```

### 2. CLI Integration

**Location:** `agent_actions/cli/main.py`

**Update debug flag handling to set source location:**

```python
# Current code (lines 96-105)
debug_mode = '--debug' in argv
verbose_mode = '--verbose' in argv or '-v' in argv

if debug_mode:
    level = 'DEBUG'
elif verbose_mode:
    level = 'INFO'
else:
    level = 'INFO'

# NEW: Add source location control
include_source = debug_mode  # True if --debug, False otherwise

# Update config initialization (around line 125)
config = LoggingConfig.from_environment()
config.default_level = level
config.file_log_level = level if debug_mode else 'DEBUG'
config.include_source_location = include_source  # NEW

# Initialize logging with config
LoggerFactory.initialize(config)
```

### 3. LoggerFactory Changes

**Location:** `agent_actions/logging/factory.py`

**Update `_create_handler()` to use config.include_source_location:**

```python
@classmethod
def _create_handler(cls, config: HandlerConfig) -> logging.Handler:
    """Create a handler from configuration."""
    # ... existing handler creation code ...

    # Set formatter based on format config
    if config.format == 'json' or config.type == 'json':
        formatter = JSONFormatter(
            include_source_location=cls._config.include_source_location
            if cls._config
            else True,
        )
    elif config.type == 'file':
        # File handler - use config setting for source location
        formatter = HumanFormatter(
            use_colors=False,
            include_source_location=cls._config.include_source_location  # NEW: use config
            if cls._config
            else False,
        )
    else:
        # Console handler - use config setting for source location
        formatter = HumanFormatter(
            use_colors=True,
            include_source_location=cls._config.include_source_location  # NEW: use config
            if cls._config
            else False,
        )

    handler.setFormatter(formatter)
    return handler
```

**Update `_create_file_handler()` to use config.include_source_location:**

```python
@classmethod
def _create_file_handler(cls) -> Optional[RotatingFileHandler]:
    """Create a rotating file handler for logging."""
    if not cls._config or not cls._config.file_handler_enabled:
        return None

    try:
        log_file_path = cls._get_log_file_path()
        if not log_file_path:
            return None

        # Create log directory if it doesn't exist
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create rotating file handler
        handler = RotatingFileHandler(
            filename=str(log_file_path),
            maxBytes=cls._config.file_max_bytes,
            backupCount=cls._config.file_backup_count,
            encoding='utf-8',
        )

        # Set handler level
        handler.setLevel(getattr(logging, cls._config.file_log_level))

        # Set formatter (no colors for file output)
        if cls._config.file_format == 'json':
            formatter = JSONFormatter(
                include_source_location=cls._config.include_source_location
            )
        else:
            formatter = HumanFormatter(
                use_colors=False,
                include_source_location=cls._config.include_source_location,  # NEW: use config
            )

        handler.setFormatter(formatter)

        # Log success to stderr only in DEBUG mode
        if cls._config and cls._config.default_level == 'DEBUG':
            print(f'Logging to file: {log_file_path}', file=sys.stderr)

        return handler

    except Exception as e:
        # Log warning to stderr and continue without file handler
        print(
            f'Warning: Failed to create file handler: {e}. '
            'Continuing with console logging only.',
            file=sys.stderr,
        )
        return None
```

### 4. HumanFormatter (No Changes Needed)

**Location:** `agent_actions/logging/formatters.py`

The existing implementation already supports `include_source_location` parameter correctly:

```python
class HumanFormatter(logging.Formatter):
    """Human-readable log formatter with optional colors and source location."""

    def __init__(
        self,
        use_colors: bool = True,
        include_source_location: bool = False,  # Already has this parameter
    ):
        super().__init__()
        self.use_colors = use_colors
        self.include_source_location = include_source_location
        # ... color setup ...

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for human readability."""
        # ... timestamp, level, context formatting ...

        # Source location (already conditional)
        if self.include_source_location:
            location = f'{record.filename}:{record.lineno}'
            if self.use_colors:
                formatted = f'{formatted} {self.DIM}({location}){self.RESET}'
            else:
                formatted = f'{formatted} ({location})'

        return formatted
```

**No changes needed** - just need to pass the correct value when creating formatters.

## Data Flow

### Normal Mode (Clean Output)

```
User runs: agent-actions run -a my_agent
    ↓
main.py: debug_mode=False, include_source=False
    ↓
LoggingConfig.from_environment()
    ↓
config.include_source_location = False
    ↓
LoggerFactory.initialize(config)
    ↓
Console: HumanFormatter(use_colors=True, include_source_location=False)
File: HumanFormatter(use_colors=False, include_source_location=False)
    ↓
Output (both console and file):
10:30:45 INFO Starting agent-actions CLI
10:30:46 INFO [abc-123] Starting agent workflow
10:30:50 INFO [abc-123] [my-agent] Processing complete
```

### Debug Mode (Developer Output)

```
User runs: agent-actions run -a my_agent --debug
    ↓
main.py: debug_mode=True, include_source=True
    ↓
LoggingConfig.from_environment()
    ↓
config.include_source_location = True
config.default_level = 'DEBUG'
    ↓
LoggerFactory.initialize(config)
    ↓
Console: HumanFormatter(use_colors=True, include_source_location=True)
File: HumanFormatter(use_colors=False, include_source_location=True)
    ↓
Output (both console and file):
10:30:45.123 DEBUG Starting agent-actions CLI (main.py:140)
10:30:46.456 DEBUG [abc-123] Starting agent workflow (agent_workflow.py:85)
10:30:50.012 INFO [abc-123] [my-agent] Processing complete (task.py:215)
```

### Environment Variable Mode

```
User runs: AGENT_ACTIONS_DEBUG=1 agent-actions run -a my_agent
    ↓
LoggingConfig.from_environment()
    ↓
Detects AGENT_ACTIONS_DEBUG=1
    ↓
config.include_source_location = True
config.default_level = 'DEBUG'
    ↓
Same as --debug flag behavior
```

## Configuration Examples

### Via Environment Variables

```bash
# Normal mode (clean output)
agent-actions run -a my_agent

# Debug mode (developer output)
AGENT_ACTIONS_DEBUG=1 agent-actions run -a my_agent

# Or with explicit log level
AGENT_ACTIONS_LOG_LEVEL=DEBUG agent-actions run -a my_agent  # DEBUG but no source location
```

### Via CLI Flags

```bash
# Normal mode
agent-actions run -a my_agent

# Verbose mode (more INFO logs, no source location)
agent-actions run -a my_agent -v

# Debug mode (DEBUG logs + source location)
agent-actions run -a my_agent --debug
```

### Via project.yaml (Future Enhancement)

```yaml
# project.yaml
logging:
  log_level: INFO
  include_source_location: false  # Clean output by default

  # Override for development
  # include_source_location: true  # Uncomment for debugging
```

## Testing Strategy

### Unit Tests

**Test normal mode:**
```python
def test_normal_mode_no_source_location():
    """Test that normal mode does not include source location."""
    config = LoggingConfig(include_source_location=False)
    LoggerFactory.initialize(config, force=True)

    logger = LoggerFactory.get_logger('test')

    with tempfile.TemporaryDirectory() as tmpdir:
        # Capture console output
        console_capture = io.StringIO()
        console_handler = logging.StreamHandler(console_capture)
        console_handler.setFormatter(
            HumanFormatter(use_colors=False, include_source_location=False)
        )
        logger.addHandler(console_handler)

        logger.info("Test message")

        output = console_capture.getvalue()

        # Should NOT contain file references
        assert "test_factory.py" not in output
        assert "(" not in output or "correlation" in output  # Allow correlation context
        assert "Test message" in output
```

**Test debug mode:**
```python
def test_debug_mode_with_source_location():
    """Test that debug mode includes source location."""
    config = LoggingConfig(
        include_source_location=True,
        default_level='DEBUG'
    )
    LoggerFactory.initialize(config, force=True)

    logger = LoggerFactory.get_logger('test')

    with tempfile.TemporaryDirectory() as tmpdir:
        # Capture console output
        console_capture = io.StringIO()
        console_handler = logging.StreamHandler(console_capture)
        console_handler.setFormatter(
            HumanFormatter(use_colors=False, include_source_location=True)
        )
        logger.addHandler(console_handler)

        logger.debug("Debug message")

        output = console_capture.getvalue()

        # SHOULD contain file references
        assert "test_factory.py" in output
        assert "(" in output and ")" in output
        assert "Debug message" in output
```

**Test environment variable:**
```python
def test_debug_env_var():
    """Test AGENT_ACTIONS_DEBUG environment variable."""
    with patch.dict(os.environ, {'AGENT_ACTIONS_DEBUG': '1'}):
        config = LoggingConfig.from_environment()

        assert config.include_source_location is True
        assert config.default_level == 'DEBUG'
```

### Integration Tests

```python
def test_cli_debug_flag():
    """Test --debug flag sets source location."""
    # Mock sys.argv
    with patch('sys.argv', ['agent-actions', 'run', '-a', 'test', '--debug']):
        # Run CLI initialization logic
        debug_mode = '--debug' in sys.argv
        include_source = debug_mode

        assert include_source is True
```

## Migration Path

### Phase 1: Fix Default Behavior (This Iteration)
1. Change `include_source_location` default from `True` to `False`
2. Update formatters to use config value
3. Update CLI to set `include_source=True` when `--debug` flag used
4. Add `AGENT_ACTIONS_DEBUG` environment variable support
5. Update tests to validate both modes

### Phase 2: Documentation (This Iteration)
1. Create `dev_artefacts/DEVELOPER_LOGGING_GUIDE.md`
2. Update `LOGGING_TESTING_GUIDE.md` with debug mode examples
3. Update CLI help text
4. Update CHANGELOG.md

### Phase 3: Future Enhancements (Later)
1. Add `--show-source` flag for explicit control (separate from --debug)
2. Add project.yaml support for `include_source_location`
3. Module-specific source location control
4. Performance profiling in debug mode

## Backward Compatibility

### Breaking Change (Minor)

**Change:** Default `include_source_location` from `True` to `False`

**Impact:**
- Users who relied on seeing `(file.py:123)` in logs will no longer see it by default
- Mitigation: Use `--debug` flag to enable it
- Justification: Cleaner user-facing output, matches industry patterns (dbt, pytest)

**Migration:**
- For users who want old behavior: `AGENT_ACTIONS_DEBUG=1` or always use `--debug`
- For library developers: Use `--debug` during development

### No Breaking Changes

- All existing `--debug` flag behavior preserved
- All existing log levels work the same
- All existing environment variables work the same
- File-based logging continues to work
- Credential redaction continues to work

## References

- Iteration 2 design: `logging-improvement-spec/design.md` (lines 1-616)
- Requirements: `logging-improvement-spec/requirements.md`
- Existing implementation: `agent_actions/logging/factory.py`
- CLI implementation: `agent_actions/cli/main.py`
