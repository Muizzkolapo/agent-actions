"""Configuration validator for agent configuration files."""

import ast
import json
import logging
import os
from pathlib import Path
from typing import Any

from agent_actions.output.response.config_fields import get_default
from agent_actions.utils.file_handler import FileHandler
from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationOrchestrator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities as ACVUtils,
)

logger = logging.getLogger(__name__)

# Alias for cleaner code
_ci_dict = ACVUtils.normalize_entry_keys_to_lowercase


class ConfigValidator(BaseValidator):
    """Validate agent configuration files with case-insensitive key handling."""

    def _check_agent_file_unique_logic(self, full_path_str: str, project_dir_str: str) -> None:
        """Check that agent file is unique in the project."""
        try:
            resolved_full_path = str(Path(full_path_str).resolve())
            all_agent_paths = FileHandler.get_all_agent_paths(project_dir_str)
            count = all_agent_paths.count(resolved_full_path)
            if count > 1:
                self.add_error(
                    f"Duplicate agent configuration file: "
                    f"{resolved_full_path} (found {count} times).",
                    field="config_path",
                    value=resolved_full_path,
                )
        except (OSError, ValueError, TypeError) as e:
            logger.exception("Error checking agent file uniqueness for %s: %s", full_path_str, e)
            self.add_error(
                f"Error checking agent file uniqueness for {full_path_str}: {e}",
                field="config_path",
                value=full_path_str,
            )

    def _collect_agent_config_files(self, project_dir_str: str) -> dict[str, list[str]]:
        """Collect all agent config files, returning name-to-paths mapping."""
        name_locations: dict[str, list[str]] = {}
        for root, dirs, _ in os.walk(project_dir_str):
            if "agent_config" not in dirs:
                continue
            agent_cfg_dir = Path(root) / "agent_config"
            if not agent_cfg_dir.is_dir():
                continue
            self._scan_config_directory(agent_cfg_dir, name_locations)
        return name_locations

    def _scan_config_directory(
        self, agent_cfg_dir: Path, name_locations: dict[str, list[str]]
    ) -> None:
        """Scan a config directory for agent YAML files."""
        for ext_pattern in ("*.yaml", "*.yml"):
            for file_obj in agent_cfg_dir.glob(ext_pattern):
                key = file_obj.stem.lower()
                name_locations.setdefault(key, []).append(str(file_obj.resolve()))

    def _find_name_conflicts(
        self,
        agent_name: str,
        name_locations: dict[str, list[str]],
        exclude_path: str | None = None,
    ) -> list[str]:
        """Find conflicting file paths for an agent name."""
        conflicts = name_locations.get(agent_name.lower(), [])
        if exclude_path:
            conflicts = [p for p in conflicts if p != exclude_path]
        return conflicts

    def _check_agent_name_unique_logic(
        self,
        agent_name_to_check: str,
        project_dir_str: str,
        current_file_path_str: str | None = None,
    ) -> None:
        """Check that agent name is unique in the project."""
        try:
            name_locations = self._collect_agent_config_files(project_dir_str)
            resolved_path = (
                str(Path(current_file_path_str).resolve()) if current_file_path_str else None
            )
            conflicts = self._find_name_conflicts(
                agent_name_to_check, name_locations, resolved_path
            )
            if conflicts:
                self.add_error(
                    f"Agent name '{agent_name_to_check}' is not unique. "
                    f"Also defined in: {', '.join(conflicts)}.",
                    field="agent_name",
                    value=agent_name_to_check,
                )
        except (OSError, ValueError, TypeError) as e:
            logger.exception(
                "Error checking agent name uniqueness for '%s': %s", agent_name_to_check, e
            )
            self.add_error(
                f"Error checking agent name uniqueness for '{agent_name_to_check}': {e}",
                field="agent_name",
                value=agent_name_to_check,
            )

    def _validate_single_agent_entry_logic(
        self, entry: dict[str, Any], cfg_ctx_name: str, proj_root: Path | None = None
    ) -> None:
        """Validate a single agent entry via the orchestrator chain."""
        orchestrator = ActionEntryValidationOrchestrator()
        orchestrator.validate_action_entry(entry, cfg_ctx_name, proj_root)

        for error in orchestrator.get_validation_errors():
            self.add_error(error)

        for warning in orchestrator.get_validation_warnings():
            self.add_warning(warning)

    def _parse_properties_dict(self, properties_part: str) -> dict[str, Any] | None:
        """Parse properties part of array[object:...] type."""
        try:
            return json.loads(properties_part)  # type: ignore[no-any-return]
        except (ValueError, json.JSONDecodeError):
            try:
                return ast.literal_eval(properties_part)  # type: ignore[no-any-return]
            except (ValueError, SyntaxError):
                return None

    def _validate_property_type(self, prop_type: Any) -> bool:
        """Validate a single property type."""
        if not isinstance(prop_type, str):
            return False
        cleaned_type = prop_type.replace("\\", "")
        base_type = cleaned_type[:-1] if cleaned_type.endswith("!") else cleaned_type
        valid_prop_types = {"string", "number", "integer", "boolean", "object"}
        return base_type in valid_prop_types

    def _is_valid_array_object_type(self, type_str: str) -> bool:
        """Validate array[object:...] type notation."""
        if not (type_str.startswith("array[object:") and type_str.endswith("]")):
            return False
        properties_dict = self._parse_properties_dict(type_str[13:-1])
        if not isinstance(properties_dict, dict):
            return False
        return all(
            isinstance(prop_name, str) and self._validate_property_type(prop_type)
            for prop_name, prop_type in properties_dict.items()
        )

    def _is_valid_schema_type(
        self, type_str: str, valid_types: set, valid_array_types: set
    ) -> bool:
        """Check if a schema type string is valid, including complex object notation."""
        if type_str in valid_types or type_str in valid_array_types:
            return True
        return self._is_valid_array_object_type(type_str)

    def _validate_agent_entries_list_logic(
        self, agent_cfg_list: Any, agent_name_ctx: str, proj_root: Path | None = None
    ) -> None:
        """Validate a list of agent entries."""
        if not isinstance(agent_cfg_list, list):
            self.add_error(
                f"Agent configuration for '{agent_name_ctx}' must be a list, "
                f"but found {type(agent_cfg_list).__name__}.",
                field="agent_config_data",
                value=type(agent_cfg_list).__name__,
            )
            return
        if not agent_cfg_list:
            self.add_warning(
                f"Agent configuration list for '{agent_name_ctx}' is empty.",
                field="agent_config_data",
            )
            return
        for entry in agent_cfg_list:
            self._validate_single_agent_entry_logic(entry, agent_name_ctx, proj_root)

    def _extract_dependencies_from_entry(self, entry: dict[str, Any]) -> set[str]:
        """Extract dependencies from an agent entry."""
        entry_ci = _ci_dict(entry) if isinstance(entry, dict) else {}
        deps: set[str] = set()
        if isinstance(entry_ci.get("dependencies"), list):
            deps.update(dep.lower() for dep in entry_ci["dependencies"] if isinstance(dep, str))
        return deps

    def _validate_config_dependencies_logic(self, full_config_data: dict[str, Any]) -> None:
        """Validate dependencies in configuration."""
        available_agents = {name.lower() for name in full_config_data}
        for agent_name, entries in full_config_data.items():
            if not isinstance(entries, list):
                continue
            deps = set()
            for entry in entries:
                if isinstance(entry, dict):
                    deps.update(self._extract_dependencies_from_entry(entry))  # type: ignore[arg-type]
            missing = deps - available_agents
            if missing:
                self.add_error(
                    f"Agent '{agent_name}' has missing dependencies: {', '.join(sorted(missing))}.",
                    field="dependencies",
                    value=list(missing),
                )

    def _build_agent_sets(
        self, agent_cfgs_map: dict[str, dict[str, Any]]
    ) -> tuple[set[str], set[str]]:
        """Return (active_agents, all_agents) sets with lowercased names."""
        active_agents = {
            name.lower()
            for name, cfg in agent_cfgs_map.items()
            if isinstance(cfg, dict)
            and _ci_dict(cfg).get("is_operational", get_default("is_operational"))
        }
        all_agents = {name.lower() for name in agent_cfgs_map}
        return active_agents, all_agents

    def _validate_single_dependency(
        self,
        agent_name: str,
        dep: Any,
        all_agents: set[str],
        active_agents: set[str],
        agent_cfgs_map: dict[str, dict[str, Any]],
    ) -> None:
        """Validate a single dependency for an agent."""
        if not isinstance(dep, str):
            self.add_error(
                f"Agent '{agent_name}' has a non-string dependency: {dep}.",
                field="dependencies",
                value=dep,
            )
            return
        dep_lc = dep.lower()
        if dep_lc not in all_agents:
            self.add_error(
                f"Active agent '{agent_name}' depends on a non-existent agent '{dep}'.",
                field="dependencies",
                value=dep,
            )
        elif dep_lc not in active_agents:
            dep_cfg_ci = _ci_dict(agent_cfgs_map.get(dep, {}))
            if not dep_cfg_ci.get("is_operational", get_default("is_operational")):
                self.add_error(
                    f"Active agent '{agent_name}' depends on an inactive agent '{dep}'.",
                    field="dependencies",
                    value=dep,
                )

    def _validate_agent_dependencies(
        self,
        agent_name: str,
        cfg: dict[str, Any],
        all_agents: set[str],
        active_agents: set[str],
        agent_cfgs_map: dict[str, dict[str, Any]],
    ) -> None:
        """Validate all dependencies for a single agent."""
        cfg_ci = _ci_dict(cfg) if isinstance(cfg, dict) else {}
        if not cfg_ci.get("is_operational", get_default("is_operational")):
            return
        deps = cfg_ci.get("dependencies", [])
        if not isinstance(deps, list):
            self.add_error(
                f"Agent '{agent_name}' has a 'dependencies' field that is not a list.",
                field="dependencies",
                value=type(deps).__name__,
            )
            return
        for dep in deps:
            self._validate_single_dependency(
                agent_name, dep, all_agents, active_agents, agent_cfgs_map
            )

    def _validate_operational_dependencies_logic(
        self, agent_cfgs_map: dict[str, dict[str, Any]]
    ) -> None:
        """Validate operational dependencies."""
        active_agents, all_agents = self._build_agent_sets(agent_cfgs_map)
        for agent_name, cfg in agent_cfgs_map.items():
            self._validate_agent_dependencies(
                agent_name, cfg, all_agents, active_agents, agent_cfgs_map
            )

    def _check_circular_dependencies_logic(self, full_config_data: dict[str, Any]) -> None:
        """Check for circular dependencies in agent configuration."""
        graph: dict[str, list[str]] = {}
        for agent_name, entries in full_config_data.items():
            if not isinstance(entries, list):
                continue
            deps = set()
            for entry in entries:
                if isinstance(entry, dict):
                    deps.update(self._extract_dependencies_from_entry(entry))  # type: ignore[arg-type]
            graph[agent_name.lower()] = list(deps)
        visited: set[str] = set()
        stack: list[str] = []

        def dfs(node: str) -> bool:
            visited.add(node)
            stack.append(node)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in stack:
                    cycle_idx = stack.index(neighbor)
                    cycle = " -> ".join(stack[cycle_idx:] + [neighbor])
                    self.add_error(
                        f"Circular dependency detected: {cycle}.",
                        field="dependencies",
                        value=cycle,
                    )
                    return True
            stack.pop()
            return False

        for n in list(graph):
            if n not in visited:
                dfs(n)
                stack.clear()  # Reset for next component (early return leaves stale entries)

    def validate(self, data: Any, config: dict[str, Any] | None = None) -> bool:
        """Run validation based on the operation key in data."""
        operation = data.get("operation", "") if isinstance(data, dict) else ""
        agent_name = data.get("agent_name", "") if isinstance(data, dict) else ""
        target = f"config:{agent_name}" if agent_name else f"config:{operation}"

        if not self._prepare_validation(data, target=target):
            return self._complete_validation()

        if not operation:
            self.add_error(
                "An 'operation' must be specified in the input 'data'.",
                field="operation",
            )
            return self._complete_validation()

        proj_dir = data.get("project_dir")
        project_root_path = Path(proj_dir).resolve() if isinstance(proj_dir, (str, Path)) else None
        operation_map = {
            "validate_agent_config_file_meta": self._validate_agent_config_file_meta_operation,
            "validate_agent_entries": self._validate_agent_entries_operation,
        }
        handler = operation_map.get(operation)
        if handler is None:
            self.add_error(
                f"Unknown operation: {operation}",
                field="operation",
                value=operation,
            )
        else:
            handler(data, project_root_path)
        return self._complete_validation()

    def _validate_config_file_access(self, cfg_file: Path) -> bool:
        """Return True if config file exists and is readable; adds errors otherwise."""
        if not self._ensure_path_exists(cfg_file):
            self.add_error(
                f"Config file does not exist: {cfg_file}",
                field="config_path",
                value=str(cfg_file),
            )
            return False
        if not self._is_file(cfg_file):
            self.add_error(
                f"Config path is not a file: {cfg_file}",
                field="config_path",
                value=str(cfg_file),
            )
            return False
        if not os.access(cfg_file, os.R_OK):
            self.add_error(
                f"Config file not readable: {cfg_file}",
                field="config_path",
                value=str(cfg_file),
            )
            return False
        return True

    def _validate_agent_config_file_meta_operation(
        self, data: dict[str, Any], project_root_path: Path | None
    ) -> None:
        """Validate agent config file metadata."""
        cfg_path = data.get("config_path")
        agent_name = data.get(
            "agent_name", Path(cfg_path).stem if isinstance(cfg_path, str) else None
        )
        if not (isinstance(cfg_path, str) and isinstance(agent_name, str) and project_root_path):
            self.add_error(
                "For 'validate_agent_config_file_meta', provide "
                "'config_path' (str), 'agent_name' (str), and 'project_dir'.",
                field="operation",
                value="validate_agent_config_file_meta",
            )
            return
        cfg_file = Path(cfg_path)
        if self._validate_config_file_access(cfg_file):
            self._check_agent_file_unique_logic(str(cfg_file.resolve()), str(project_root_path))
            self._check_agent_name_unique_logic(
                agent_name, str(project_root_path), str(cfg_file.resolve())
            )

    def _validate_agent_entries_operation(
        self, data: dict[str, Any], project_root_path: Path | None
    ) -> None:
        """Validate agent entries operation."""
        cfg_list = data.get("agent_config_data")
        ctx_name = data.get("agent_name_context")
        if cfg_list is None or not isinstance(ctx_name, str):
            self.add_error(
                "For 'validate_agent_entries', provide "
                "'agent_config_data' and 'agent_name_context'.",
                field="operation",
                value="validate_agent_entries",
            )
            return
        self._validate_agent_entries_list_logic(cfg_list, ctx_name, project_root_path)
