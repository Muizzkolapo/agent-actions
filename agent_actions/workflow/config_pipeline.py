"""Config loading, schema validation, and UDF discovery for workflow initialization."""

import logging
from pathlib import Path
from typing import Any

from rich.console import Console

from agent_actions.config.manager import ConfigManager
from agent_actions.input.loaders.udf import discover_udfs
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    UDFDiscoveryCompleteEvent,
    UDFDiscoveryStartEvent,
    WorkflowInitializationStartEvent,
)
from agent_actions.workflow.models import VirtualAction, WorkflowMetadata, WorkflowRuntimeConfig

logger = logging.getLogger(__name__)


def _run_config_stage(fn: Any, stage: str, manager: ConfigManager, *args: Any) -> Any:
    """Call *fn* and enrich any exception with the failing stage name.

    Uses ``pipeline_stage`` instead of ``operation`` so inner handlers
    (e.g. ``_load_single_config`` setting ``operation: template_rendering``)
    are not overwritten.
    """
    try:
        return fn(*args)
    except Exception as e:
        agent = getattr(manager, "agent_name", "unknown")
        logger.debug("Config stage '%s' failed for agent '%s': %s", stage, agent, e)
        if not hasattr(e, "context") or not isinstance(e.context, dict):  # type: ignore[attr-defined]
            e.context = {}  # type: ignore[attr-defined]
        e.context.update(  # type: ignore[attr-defined]
            {
                "agent": agent,
                "pipeline_stage": stage,
            }
        )
        raise


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
    _run_config_stage(manager.load_configs, "load_configs", manager)
    _run_config_stage(manager.validate_agent_name, "validate_agent_name", manager)
    # Discover UDFs BEFORE expanding actions (which needs UDF metadata)
    discover_workflow_udfs(config, console)

    user_agents = _run_config_stage(manager.get_user_agents, "get_user_agents", manager)
    _run_config_stage(manager.merge_agent_configs, "merge_agent_configs", manager, user_agents)

    virtual_actions = _run_config_stage(
        _inject_upstream_virtual_actions, "inject_upstream_virtual_actions", manager, manager
    )

    virtual_action_names = set(virtual_actions.keys()) if virtual_actions else set()
    _run_config_stage(
        manager.determine_execution_order,
        "determine_execution_order",
        manager,
        virtual_action_names,
    )

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
        virtual_actions=virtual_actions,
    )


def _inject_upstream_virtual_actions(
    manager: ConfigManager,
) -> dict[str, VirtualAction]:
    """Parse ``upstream`` declarations and build virtual action map.

    Returns:
        Dict mapping action name to ``VirtualAction``.
    """
    if manager.user_config is None:
        return {}

    upstream_refs = manager.user_config.get("upstream")
    if not upstream_refs or not isinstance(upstream_refs, list):
        return {}

    # Filter to well-formed refs once, reuse for validation and building
    parsed_refs = [ref for ref in upstream_refs if isinstance(ref, dict) and "workflow" in ref]
    if not parsed_refs:
        return {}

    if manager.project_root:
        from agent_actions.workflow.orchestrator import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(manager.project_root)
        orchestrator.validate_upstream_refs(manager.agent_name or "unknown", parsed_refs)

    virtual_actions: dict[str, VirtualAction] = {}
    for ref in parsed_refs:
        workflow_name = ref["workflow"]
        for action_name in ref.get("actions", []):
            virtual_actions[action_name] = VirtualAction(
                source_workflow=workflow_name,
                action_name=action_name,
            )

    return virtual_actions


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
        label = "Tool" if total_udfs == 1 else "Tools"
        console.print(f"[green]\u2705 Discovered {total_udfs} {label}[/green]")
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
