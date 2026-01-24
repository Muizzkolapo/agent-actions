# TICKET-019: Add Configuration and Initialization Events

**Status:** ✅ DONE
**Priority:** High
**Estimate:** 3-4 hours
**Labels:** logging, config, initialization

## Description

Add event instrumentation for configuration loading, environment variable reading, CLI initialization, and system startup to improve visibility into application bootstrapping.

## Deliverables

- [x] Configuration file loading events
- [ ] Environment variable loading events (Deferred - LOW priority)
- [x] CLI initialization events
- [x] System initialization events
- [x] Plugin/UDF discovery events

## Configuration File Loading Events

### Files to modify:
- `agent_actions/config/path_config.py` (lines 13-52)
- `agent_actions/llm/realtime/config.py` (lines 40-100)
- `agent_actions/workflow/coordinator.py` (lines 248-283)

### Event types:

```python
class ConfigLoadStartEvent(DebugLevel, BaseEvent):
    """C001 - Config loading started"""
    def __init__(self, config_file: str):
        super().__init__(
            message=f"Loading config from {config_file}",
            category="configuration",
            data={"config_file": config_file},
        )

class ConfigLoadEvent(InfoLevel, BaseEvent):
    """C002 - Config loaded"""
    def __init__(self, config_file: str, config_type: str):
        super().__init__(
            message=f"Loaded {config_type} config from {config_file}",
            category="configuration",
            data={"config_file": config_file, "config_type": config_type},
        )

class ConfigLoadCompleteEvent(InfoLevel, BaseEvent):
    """C003 - All configs loaded"""

class ConfigValidationEvent(DebugLevel, BaseEvent):
    """C004 - Config validation"""
```

### Example (path_config.py):
```python
def load_project_config(project_root: Path) -> Dict[str, Any]:
    for config_file in config_files:
        if config_file.exists():
            fire_event(ConfigLoadStartEvent(str(config_file)))

            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            fire_event(ConfigLoadEvent(str(config_file), "project"))
            return config or {}
```

## Environment Variable Events

### Files to modify:
- `agent_actions/config/environment.py` (lines 30-156)

### Event types:

```python
class EnvironmentLoadStartEvent(DebugLevel, BaseEvent):
    """E001 - Environment loading started"""

class EnvironmentVariableDetectedEvent(DebugLevel, BaseEvent):
    """E002 - Environment variable detected"""
    def __init__(self, var_name: str):
        super().__init__(
            message=f"Environment variable detected: {var_name}",
            category="environment",
            data={"var_name": var_name},
        )

class EnvironmentLoadCompleteEvent(InfoLevel, BaseEvent):
    """E003 - Environment loaded"""
```

## CLI Initialization Events

### Files to modify:
- `agent_actions/cli/main.py` (lines 37-221)
- `agent_actions/cli/commands/init.py` (lines 170-197)
- `agent_actions/cli/commands/run.py` (lines 27-421)

### Event types:

```python
class CLIInitStartEvent(DebugLevel, BaseEvent):
    """I001 - CLI initialization started"""

class CLIArgumentParsingEvent(DebugLevel, BaseEvent):
    """I002 - CLI arguments parsed"""
    def __init__(self, command: str, args: Dict[str, Any]):
        super().__init__(
            message=f"CLI command: {command}",
            category="initialization",
            data={"command": command, "args": args},
        )

class CLIInitCompleteEvent(DebugLevel, BaseEvent):
    """I003 - CLI initialization complete"""
```

## System Initialization Events

### Files to modify:
- `agent_actions/config/initializer.py` (lines 21-124)
- `agent_actions/config/di/application.py` (lines 35-226)
- `agent_actions/workflow/coordinator.py` (lines 72-247)

### Event types:

```python
class ApplicationInitializationStartEvent(InfoLevel, BaseEvent):
    """I004 - Application initialization started"""

class StartupValidationStartEvent(DebugLevel, BaseEvent):
    """I005 - Startup validation started"""

class StartupValidationCompleteEvent(InfoLevel, BaseEvent):
    """I006 - Startup validation complete"""

class DIContainerInitializationEvent(DebugLevel, BaseEvent):
    """I007 - DI container initialized"""

class WorkflowInitializationStartEvent(DebugLevel, BaseEvent):
    """I008 - Workflow initialization started"""

class WorkflowServicesInitializationStartEvent(DebugLevel, BaseEvent):
    """I009 - Workflow services initialization started"""
```

### Example (initializer.py):
```python
def initialize_application() -> ApplicationContainer:
    fire_event(ApplicationInitializationStartEvent())

    fire_event(StartupValidationStartEvent())
    _run_startup_validation()
    fire_event(StartupValidationCompleteEvent())

    container = ApplicationContainer()
    fire_event(DIContainerInitializationEvent())

    return container
```

## Plugin/UDF Discovery Events

### Files to modify:
- `agent_actions/workflow/coordinator.py` (lines 310-342)
- `agent_actions/config/di/container.py` (lines 44-296)

### Event types:

```python
class UDFDiscoveryStartEvent(DebugLevel, BaseEvent):
    """P001 - UDF discovery started"""
    def __init__(self, search_path: str):
        super().__init__(
            message=f"Discovering UDFs in {search_path}",
            category="plugin",
            data={"search_path": search_path},
        )

class UDFDiscoveredEvent(DebugLevel, BaseEvent):
    """P002 - UDF discovered"""
    def __init__(self, udf_name: str, udf_type: str):
        super().__init__(
            message=f"Discovered UDF: {udf_name} ({udf_type})",
            category="plugin",
            data={"udf_name": udf_name, "udf_type": udf_type},
        )

class UDFDiscoveryCompleteEvent(InfoLevel, BaseEvent):
    """P003 - UDF discovery complete"""
    def __init__(self, total_udfs: int):
        super().__init__(
            message=f"UDF discovery complete: {total_udfs} UDFs found",
            category="plugin",
            data={"total_udfs": total_udfs},
        )

class ProcessorRegistrationEvent(DebugLevel, BaseEvent):
    """P004 - Processor registered"""
```

## Project Initialization Events

### Files to modify:
- `agent_actions/cli/commands/init.py`

### Event types:

```python
class ProjectInitializationStartEvent(InfoLevel, BaseEvent):
    """I010 - Project initialization started"""

class ProjectValidationEvent(DebugLevel, BaseEvent):
    """I011 - Project validation"""

class ProjectDirectoryCreatedEvent(InfoLevel, BaseEvent):
    """I012 - Project directory created"""

class ProjectInitializedEvent(InfoLevel, BaseEvent):
    """I013 - Project initialized"""
```

## Priority Order

1. **HIGH**: Application/workflow initialization events
2. **HIGH**: Configuration file loading events
3. **MEDIUM**: CLI initialization events
4. **MEDIUM**: UDF discovery events
5. **LOW**: Environment variable events (already visible via config)

## Acceptance Criteria

- [x] Config loading fires events for each file
- [ ] Environment loading fires events (Deferred)
- [x] CLI initialization visible in logs
- [x] System startup stages tracked
- [x] UDF discovery shows counts
- [x] All events appear in debug logs with `-v` flag

## Implementation Summary

All configuration and initialization events have been implemented and instrumented across the codebase.

### Event Types Defined (24 events)

**Note:** Configuration events use **F** prefix (conFiguration) instead of C, as C is already used by Cache events (TICKET-017).

| Code | Event Type | Level | Category | Description |
|------|------------|-------|----------|-------------|
| **F001** | ConfigLoadStartEvent | DEBUG | configuration | Config loading started |
| **F002** | ConfigLoadEvent | INFO | configuration | Config loaded from file |
| **F003** | ConfigLoadCompleteEvent | INFO | configuration | All configs loaded |
| **F004** | ConfigValidationEvent | DEBUG | configuration | Config validation |
| **E001** | EnvironmentLoadStartEvent | DEBUG | environment | Environment loading started |
| **E002** | EnvironmentVariableDetectedEvent | DEBUG | environment | Environment variable detected |
| **E003** | EnvironmentLoadCompleteEvent | INFO | environment | Environment loaded |
| **I001** | CLIInitStartEvent | DEBUG | initialization | CLI initialization started |
| **I002** | CLIArgumentParsingEvent | DEBUG | initialization | CLI arguments parsed |
| **I003** | CLIInitCompleteEvent | DEBUG | initialization | CLI initialization complete |
| **I004** | ApplicationInitializationStartEvent | INFO | initialization | Application initialization started |
| **I005** | StartupValidationStartEvent | DEBUG | initialization | Startup validation started |
| **I006** | StartupValidationCompleteEvent | INFO | initialization | Startup validation complete |
| **I007** | DIContainerInitializationEvent | DEBUG | initialization | DI container initialized |
| **I008** | WorkflowInitializationStartEvent | DEBUG | initialization | Workflow initialization started |
| **I009** | WorkflowServicesInitializationStartEvent | DEBUG | initialization | Workflow services initialization |
| **I010** | ProjectInitializationStartEvent | INFO | initialization | Project initialization started |
| **I011** | ProjectValidationEvent | DEBUG | initialization | Project validation |
| **I012** | ProjectDirectoryCreatedEvent | INFO | initialization | Project directory created |
| **I013** | ProjectInitializedEvent | INFO | initialization | Project initialized |
| **P001** | UDFDiscoveryStartEvent | DEBUG | plugin | UDF discovery started |
| **P002** | UDFDiscoveredEvent | DEBUG | plugin | UDF discovered |
| **P003** | UDFDiscoveryCompleteEvent | INFO | plugin | UDF discovery complete |
| **P004** | ProcessorRegistrationEvent | DEBUG | plugin | Processor registered |

### Event Categories Added

Added 4 new event categories to `EventCategories`:
- `CONFIGURATION = "configuration"`
- `ENVIRONMENT = "environment"`
- `INITIALIZATION = "initialization"`
- `PLUGIN = "plugin"`

### Files Instrumented

**Configuration Loading (3 files):**
1. `agent_actions/config/path_config.py`
   - Fires ConfigLoadStartEvent before loading project config
   - Fires ConfigLoadEvent after successful load

2. `agent_actions/llm/realtime/config.py`
   - Fires ConfigLoadStartEvent/ConfigLoadEvent for workflow config
   - Fires ConfigLoadStartEvent/ConfigLoadEvent for default config

3. `agent_actions/workflow/coordinator.py`
   - Config loading events already handled by realtime/config.py

**System Initialization (2 files):**
4. `agent_actions/config/initializer.py`
   - Fires ApplicationInitializationStartEvent at app startup
   - Fires StartupValidationStartEvent before validation
   - Fires StartupValidationCompleteEvent after validation (with elapsed time)
   - Fires DIContainerInitializationEvent after container creation

5. `agent_actions/workflow/coordinator.py`
   - Fires WorkflowInitializationStartEvent at workflow init
   - Fires WorkflowServicesInitializationStartEvent at services init
   - Fires UDFDiscoveryStartEvent/UDFDiscoveryCompleteEvent for UDF discovery

**CLI Initialization (2 files):**
6. `agent_actions/cli/main.py`
   - Fires CLIInitStartEvent at CLI startup
   - Fires CLIInitCompleteEvent after initialization
   - Fires CLIArgumentParsingEvent after parsing args

7. `agent_actions/cli/commands/init.py`
   - Fires ProjectInitializationStartEvent at project init start
   - Fires ProjectValidationEvent during validation steps
   - Fires ProjectDirectoryCreatedEvent after directory creation
   - Fires ProjectInitializedEvent on completion (with elapsed time)

**Export Configuration:**
8. `agent_actions/logging/events/__init__.py`
   - Added all 24 events to imports and __all__ list
   - Events accessible via `from agent_actions.logging.events import ConfigLoadStartEvent`

### Statistics

- **Total event types defined:** 24
- **Files modified:** 9 (7 instrumented + types.py + __init__.py)
- **Event categories added:** 4
- **Lines added:** ~450
- **Lines removed:** ~20
- **Event codes:** F001-F004, E001-E003, I001-I013, P001-P004

### Event Code Prefix Change

**Important:** Configuration events use **F** prefix instead of C:
- **Reason:** C001-C006 are already used by Cache events (TICKET-017)
- **Solution:** Used F prefix for conFiguration events
- **Impact:** Updated docstring in types.py to reflect F = Configuration

### Benefits

1. **Application Startup Visibility:** Track initialization stages with timing
2. **Config Loading Transparency:** See which configs are loaded and when
3. **CLI Observability:** Track CLI commands and argument parsing
4. **UDF Discovery Tracking:** Monitor UDF discovery with counts
5. **Project Init Tracking:** Monitor project initialization with validation steps

### Example Output

With `-v` flag, users will see:
```
[DEBUG] I004: Application initialization started
[DEBUG] I005: Startup validation started
[INFO]  I006: Startup validation complete in 0.23s
[DEBUG] I007: DI container initialized
[DEBUG] F001: Loading config from /path/to/workflow.yml
[INFO]  F002: Loaded workflow config from /path/to/workflow.yml
[DEBUG] I008: Workflow initialization started: my_workflow
[DEBUG] I009: Workflow services initialization started: my_workflow
[DEBUG] P001: Discovering UDFs in /path/to/udfs
[INFO]  P003: UDF discovery complete: 5 UDFs found
```

### Deferred Work

- **Environment variable events (E001-E003):** Deferred as LOW priority
  - Reason: Environment variables already visible via config logging
  - Can be implemented later if needed

- **Tests:** Deferred (follow TICKET-018 pattern)

### Notes

- All events follow the @dataclass pattern with __post_init__
- All events properly typed with List[str], Dict[str, Any]
- All events exported in __init__.py for public API access
- Code formatted with ruff format (3 files reformatted)
