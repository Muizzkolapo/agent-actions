"""Configuration, environment, initialization, and plugin events (F/E/I/P prefixes)."""

from dataclasses import dataclass, field
from typing import Any

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories

__all__ = [
    "ConfigLoadStartEvent",
    "ConfigLoadEvent",
    "CLIInitStartEvent",
    "CLIArgumentParsingEvent",
    "CLIInitCompleteEvent",
    "WorkflowInitializationStartEvent",
    "WorkflowServicesInitializationStartEvent",
    "ProjectInitializationStartEvent",
    "ProjectValidationEvent",
    "ProjectDirectoryCreatedEvent",
    "ProjectInitializedEvent",
    "UDFDiscoveryStartEvent",
    "UDFDiscoveryCompleteEvent",
]


@dataclass
class ConfigLoadStartEvent(BaseEvent):
    """Fired when configuration loading starts."""

    config_file: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.CONFIGURATION
        self.message = f"Loading config from {self.config_file}"
        self.data = {
            "config_file": self.config_file,
        }

    @property
    def code(self) -> str:
        return "F001"


@dataclass
class ConfigLoadEvent(BaseEvent):
    """Fired when configuration is loaded successfully."""

    config_file: str = ""
    config_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.CONFIGURATION
        self.message = f"Loaded {self.config_type} config from {self.config_file}"
        self.data = {
            "config_file": self.config_file,
            "config_type": self.config_type,
        }

    @property
    def code(self) -> str:
        return "F002"


@dataclass
class CLIInitStartEvent(BaseEvent):
    """Fired when CLI initialization starts."""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = "CLI initialization started"
        self.data = {}

    @property
    def code(self) -> str:
        return "I001"


@dataclass
class CLIArgumentParsingEvent(BaseEvent):
    """Fired before CLI arguments are parsed (raw argv, not Click-parsed)."""

    command: str = ""
    args: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = f"CLI invoked with command: {self.command}"
        self.data = {
            "command": self.command,
            "args": self.args,
        }

    @property
    def code(self) -> str:
        return "I002"


@dataclass
class CLIInitCompleteEvent(BaseEvent):
    """Fired when CLI initialization completes."""

    command: str = ""
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = (
            f"CLI initialization complete for '{self.command}' in {self.elapsed_time:.2f}s"
        )
        self.data = {
            "command": self.command,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "I003"


@dataclass
class WorkflowInitializationStartEvent(BaseEvent):
    """Fired when workflow initialization starts."""

    workflow_name: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = f"Workflow initialization started: {self.workflow_name}"
        self.data = {
            "workflow_name": self.workflow_name,
        }

    @property
    def code(self) -> str:
        return "I008"


@dataclass
class WorkflowServicesInitializationStartEvent(BaseEvent):
    """Fired when workflow services initialization starts."""

    workflow_name: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = f"Workflow services initialization started: {self.workflow_name}"
        self.data = {
            "workflow_name": self.workflow_name,
        }

    @property
    def code(self) -> str:
        return "I009"


@dataclass
class ProjectInitializationStartEvent(BaseEvent):
    """Fired when project initialization starts."""

    project_path: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.INITIALIZATION
        self.message = f"Project initialization started: {self.project_path}"
        self.data = {
            "project_path": self.project_path,
        }

    @property
    def code(self) -> str:
        return "I010"


@dataclass
class ProjectValidationEvent(BaseEvent):
    """Fired during project validation."""

    validation_target: str = ""
    result: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.INITIALIZATION
        self.message = f"Project validation ({self.validation_target}): {self.result}"
        self.data = {
            "validation_target": self.validation_target,
            "result": self.result,
        }

    @property
    def code(self) -> str:
        return "I011"


@dataclass
class ProjectDirectoryCreatedEvent(BaseEvent):
    """Fired when project directory is created."""

    directory_path: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.INITIALIZATION
        self.message = f"Project directory created: {self.directory_path}"
        self.data = {
            "directory_path": self.directory_path,
        }

    @property
    def code(self) -> str:
        return "I012"


@dataclass
class ProjectInitializedEvent(BaseEvent):
    """Fired when project initialization completes."""

    project_path: str = ""
    project_name: str = ""
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.INITIALIZATION
        name_part = f" ({self.project_name})" if self.project_name else ""
        self.message = (
            f"Project initialized{name_part}: {self.project_path} in {self.elapsed_time:.2f}s"
        )
        self.data = {
            "project_path": self.project_path,
            "project_name": self.project_name,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "I013"


@dataclass
class UDFDiscoveryStartEvent(BaseEvent):
    """Fired when UDF discovery starts."""

    search_path: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.PLUGIN
        self.message = f"Discovering Tools in {self.search_path}"
        self.data = {
            "search_path": self.search_path,
        }

    @property
    def code(self) -> str:
        return "P001"


@dataclass
class UDFDiscoveryCompleteEvent(BaseEvent):
    """Fired when UDF discovery completes."""

    total_udfs: int = 0
    elapsed_time: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.PLUGIN
        self.message = (
            f"UDF discovery complete: {self.total_udfs} UDFs found in {self.elapsed_time:.2f}s"
        )
        self.data = {
            "total_udfs": self.total_udfs,
            "elapsed_time": self.elapsed_time,
        }

    @property
    def code(self) -> str:
        return "P003"
