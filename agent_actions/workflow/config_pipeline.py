"""Config loading, schema validation, and UDF discovery for workflow initialization."""

import logging
from pathlib import Path

from rich.console import Console

from agent_actions.config.manager import ConfigManager
from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.input.loaders.udf import discover_udfs
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    UDFDiscoveryCompleteEvent,
    UDFDiscoveryStartEvent,
    WorkflowInitializationStartEvent,
)
from agent_actions.workflow.models import WorkflowMetadata, WorkflowRuntimeConfig

logger = logging.getLogger(__name__)


def load_workflow_configs(config: WorkflowRuntimeConfig, console: Console) -> WorkflowMetadata:
    """Load and process configuration files, discover UDFs, return metadata.

    Fires ``WorkflowInitializationStartEvent`` and creates the
    ``ConfigManager`` when one is not already present on *config*.
    """
    fire_event(
        WorkflowInitializationStartEvent(
            workflow_name=config.manager.agent_name if config.manager else "unknown"
        )
    )

    if config.manager is None:
        config.manager = ConfigManager(
            config.paths.constructor_path,
            config.paths.default_path,
            project_root=config.project_root,
        )

    manager = config.manager
    manager.load_configs()
    manager.validate_agent_name()
    manager.check_child_pipeline()

    # Discover UDFs BEFORE expanding actions (which needs UDF metadata)
    discover_workflow_udfs(config, console)

    user_agents = manager.get_user_agents()
    manager.merge_agent_configs(user_agents)
    manager.determine_execution_order()

    execution_order = manager.execution_order
    action_configs = manager.get_all_agent_configs_as_dicts()
    action_indices = {action: i for i, action in enumerate(execution_order)}

    # Add idx and workflow_config_path fields to each action config
    for action_name, action_config in action_configs.items():
        # Skip None configs (defensive check for malformed dictionaries)
        if action_config is None:
            continue
        if action_name in action_indices:
            action_config["idx"] = action_indices[action_name]
        # Add workflow config path for static data loading
        action_config["workflow_config_path"] = config.paths.constructor_path
        if config.project_root:
            action_config["_project_root"] = str(config.project_root)

    return WorkflowMetadata(
        agent_name=manager.agent_name,
        execution_order=execution_order,
        action_indices=action_indices,
        action_configs=action_configs,
        child_pipeline=manager.child_pipeline,
    )


def validate_schema_files(action_configs: dict, config: WorkflowRuntimeConfig) -> None:
    """Validate that all referenced schema files exist (fail-fast).

    Raises:
        ConfigValidationError: If any referenced schema files are missing.
    """
    manager = config.manager
    project_root = (manager.project_root if manager else None) or config.project_root or Path.cwd()
    schema_dir = project_root / "schema"

    missing_schemas = []

    for action_name, action_config in action_configs.items():
        if action_config is None:
            continue

        schema_name = action_config.get("schema_name")
        if schema_name:
            schema_file = schema_dir / f"{schema_name}.yml"
            if not schema_file.exists():
                missing_schemas.append((action_name, schema_name, schema_file))

    if missing_schemas:
        error_lines = ["Schema validation failed. The following schema files are missing:"]
        for action_name, schema_name, schema_file in missing_schemas:
            error_lines.append(f"  - Action '{action_name}': schema '{schema_name}.yml'")
            error_lines.append(f"    Expected at: {schema_file}")

        error_lines.append("")
        error_lines.append("Please ensure all schema files exist in the schema/ directory.")

        raise ConfigValidationError(
            "\n".join(error_lines),
            context={
                "missing_schemas": [
                    {"action": a, "schema": s, "path": str(p)} for a, s, p in missing_schemas
                ],
                "schema_dir": str(schema_dir),
            },
        )


def discover_workflow_udfs(config: WorkflowRuntimeConfig, console: Console) -> None:
    """Discover user-defined functions from configured paths."""
    total_udfs = 0
    if config.paths.user_code_path:
        total_udfs = _discover_udfs_from_path(
            config.paths.user_code_path, config.project_root, console
        )
    elif config.manager and config.manager.tool_path:
        for path in config.manager.tool_path:
            count = _discover_udfs_from_path(path, config.project_root, console)
            total_udfs += count

    if total_udfs > 0:
        console.print(f"[green]\u2705 Discovered {total_udfs} Tools[/green]")
        fire_event(UDFDiscoveryCompleteEvent(total_udfs=total_udfs))


def _discover_udfs_from_path(path: str, project_root: Path | None, console: Console) -> int:
    """Discover UDFs from a specific path."""
    p = Path(path)
    if p.is_absolute():
        abs_path = p
    elif project_root:
        abs_path = (project_root / p).resolve()
    else:
        abs_path = p.absolute()

    if abs_path.exists() and abs_path.is_dir():
        fire_event(UDFDiscoveryStartEvent(search_path=str(abs_path)))
        console.print(f"[cyan]\U0001f50d Discovering Tools in {abs_path}...[/cyan]")
        registry = discover_udfs(abs_path)
        return len(registry)

    return 0
