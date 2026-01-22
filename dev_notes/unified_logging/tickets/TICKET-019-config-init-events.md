# TICKET-019: Add Configuration and Initialization Events

**Status:** 🔲 TODO
**Priority:** High
**Estimate:** 3-4 hours
**Labels:** logging, config, initialization

## Description

Add event instrumentation for configuration loading, environment variable reading, CLI initialization, and system startup to improve visibility into application bootstrapping.

## Deliverables

- [ ] Configuration file loading events
- [ ] Environment variable loading events
- [ ] CLI initialization events
- [ ] System initialization events
- [ ] Plugin/UDF discovery events

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

- [ ] Config loading fires events for each file
- [ ] Environment loading fires events
- [ ] CLI initialization visible in logs
- [ ] System startup stages tracked
- [ ] UDF discovery shows counts
- [ ] All events appear in debug logs with `-v` flag
