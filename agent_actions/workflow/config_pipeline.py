"""Config loading, schema validation, and UDF discovery for workflow initialization."""

import logging
import os
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
from agent_actions.workflow.models import CompilationResult, WorkflowMetadata, WorkflowRuntimeConfig

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

    When the ``AGAC_COMPILED_CROSS_WORKFLOW=1`` environment variable is set
    and the workflow has cross-workflow dependencies (or ``--upstream`` /
    ``--downstream`` flags), the compiler merges all involved workflows into
    a single DAG before the normal config pipeline runs.
    """
    fire_event(
        WorkflowInitializationStartEvent(
            workflow_name=config.manager.agent_name if config.manager else "unknown"
        )
    )

    # Feature-gated cross-workflow compilation.
    if os.environ.get("AGAC_COMPILED_CROSS_WORKFLOW") == "1":
        compilation = _maybe_compile(config)
        if compilation is not None:
            return _load_compiled_workflow(config, compilation, console)

    if config.manager is None:
        config.manager = ConfigManager(
            config.paths.constructor_path,
            config.paths.default_path,
            project_root=config.project_root,
        )

    manager = config.manager
    _run_config_stage(manager.load_configs, "load_configs", manager)
    _run_config_stage(manager.validate_agent_name, "validate_agent_name", manager)
    _run_config_stage(manager.check_child_pipeline, "check_child_pipeline", manager)

    # Discover UDFs BEFORE expanding actions (which needs UDF metadata)
    discover_workflow_udfs(config, console)

    user_agents = _run_config_stage(manager.get_user_agents, "get_user_agents", manager)
    _run_config_stage(manager.merge_agent_configs, "merge_agent_configs", manager, user_agents)
    _run_config_stage(manager.determine_execution_order, "determine_execution_order", manager)

    execution_order = manager.execution_order
    action_configs = manager.get_all_agent_configs_as_dicts()
    action_indices = {action: i for i, action in enumerate(execution_order)}

    # Detect which actions had cross-workflow dependencies (dict deps that
    # Pydantic strips).  The runner needs this flag to select the correct
    # strategy — cross-workflow first actions are intermediate, not initial.
    cross_wf_actions: set[str] = set()
    for raw_action in (manager.user_config or {}).get("actions", []):
        if not isinstance(raw_action, dict):
            continue
        deps = raw_action.get("depends_on") or raw_action.get("dependencies", [])
        if isinstance(deps, list) and any(isinstance(d, dict) for d in deps):
            name = raw_action.get("name")
            if name:
                cross_wf_actions.add(name)

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
        if action_name in cross_wf_actions:
            action_config["_has_cross_workflow_deps"] = True

    return WorkflowMetadata(
        agent_name=manager.agent_name,
        execution_order=execution_order,
        action_indices=action_indices,
        action_configs=action_configs,
        child_pipeline=manager.child_pipeline,
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


# ---------------------------------------------------------------------------
# Cross-workflow compilation (feature-gated)
# ---------------------------------------------------------------------------


def _maybe_compile(config: WorkflowRuntimeConfig) -> CompilationResult | None:
    """Return a CompilationResult if cross-workflow compilation is needed, else None.

    Reads the primary workflow YAML (without template rendering) to check for
    dict dependencies.  If found — or if ``--upstream`` / ``--downstream``
    flags are set — compiles all involved workflows into a single DAG.
    """
    from agent_actions.workflow.compiler import compile_workflows, needs_compilation

    primary_path = Path(config.paths.constructor_path)

    # Quick check: does the raw YAML have cross-workflow deps?
    import yaml

    try:
        with open(primary_path, encoding="utf-8") as f:
            raw_config = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        logger.debug("Compilation gate check failed, deferring to normal pipeline: %s", e)
        return None

    if not needs_compilation(raw_config, config.run_upstream, config.run_downstream):
        return None

    # Derive workflows_root: .../workflows/CURRENT/agent_config/x.yml → parents[2]
    if len(primary_path.parents) < 3:
        logger.warning("Config path too shallow for compilation: %s", primary_path)
        return None

    workflows_root = primary_path.parents[2]
    logger.info("Compiling cross-workflow DAG from %s", workflows_root)

    return compile_workflows(
        primary_path,
        workflows_root,
        run_upstream=config.run_upstream,
        run_downstream=config.run_downstream,
    )


def _load_compiled_workflow(
    config: WorkflowRuntimeConfig,
    compilation: CompilationResult,
    console: Console,
) -> WorkflowMetadata:
    """Build WorkflowMetadata from a compiled multi-workflow DAG.

    Creates a ConfigManager with a synthetic merged config, runs the normal
    validation and expansion pipeline, then attaches compilation metadata.
    """
    # Build a synthetic config dict from the compiled actions.
    merged_config: dict[str, Any] = {
        "name": compilation.primary_workflow,
        "actions": compilation.merged_actions,
    }

    # Create a ConfigManager with the primary workflow's paths but override
    # user_config with the merged config.
    if config.manager is None:
        config.manager = ConfigManager(
            config.paths.constructor_path,
            config.paths.default_path,
            project_root=config.project_root,
        )

    manager = config.manager
    _run_config_stage(manager.load_configs, "load_configs", manager)
    _run_config_stage(manager.validate_agent_name, "validate_agent_name", manager)
    _run_config_stage(manager.check_child_pipeline, "check_child_pipeline", manager)

    # Override user_config with the compiled merged config.
    manager.user_config = merged_config

    # Discover UDFs from all involved workflows.
    discover_workflow_udfs(config, console)
    for wf_name in compilation.involved_workflows:
        meta = compilation.action_metadata
        # Find tool paths from each workflow's directory.
        for action_meta in meta.values():
            if action_meta.source_workflow == wf_name:
                wf_dir = action_meta.source_workflow_dir
                tools_dir = wf_dir / "tools"
                if tools_dir.is_dir():
                    _discover_udfs_from_path(str(tools_dir), config.project_root, console)
                break

    user_agents = _run_config_stage(manager.get_user_agents, "get_user_agents", manager)
    _run_config_stage(manager.merge_agent_configs, "merge_agent_configs", manager, user_agents)
    _run_config_stage(manager.determine_execution_order, "determine_execution_order", manager)

    execution_order = manager.execution_order
    action_configs = manager.get_all_agent_configs_as_dicts()
    action_indices = {action: i for i, action in enumerate(execution_order)}

    # Inject metadata into each action config.
    for action_name, action_config in action_configs.items():
        if action_config is None:
            continue
        if action_name in action_indices:
            action_config["idx"] = action_indices[action_name]
        action_config["workflow_config_path"] = config.paths.constructor_path
        if config.project_root:
            action_config["_project_root"] = str(config.project_root)

        # Propagate source workflow metadata from compilation.
        if action_name in compilation.action_metadata:
            meta = compilation.action_metadata[action_name]
            action_config["_source_workflow_dir"] = str(meta.source_workflow_dir)
            action_config["_source_workflow_name"] = meta.source_workflow

    return WorkflowMetadata(
        agent_name=manager.agent_name,
        execution_order=execution_order,
        action_indices=action_indices,
        action_configs=action_configs,
        child_pipeline=manager.child_pipeline,
        compilation=compilation,
    )
