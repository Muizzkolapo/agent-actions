"""Configuration validator for agent configuration files."""

import ast
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent_actions.file_io.file_handler import FileHandler
from agent_actions.response_processing.config_types import AgentConfigMap
from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.orchestration.agent_entry_validation_orchestrator import (
    AgentEntryValidationOrchestrator,
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities as ACVUtils,
)

logger = logging.getLogger(__name__)

# Aliases for cleaner code
_ci_dict = ACVUtils.normalize_entry_keys_to_lowercase
_ci_get = ACVUtils.get_case_insensitive_value


class ConfigValidator(BaseValidator):
    """Validate agent configuration files with case-insensitive key handling.

    Business rules are unchanged; only comparisons are agnostic to key case
    or value case.

    Note: Configuration constants are now centralized in AgentConfigValidationUtilities.
    """

    def _check_agent_file_unique_logic(self, full_path_str: str, project_dir_str: str) -> None:
        """Check that agent file is unique in the project."""
        try:
            resolved_full_path = str(Path(full_path_str).resolve())
            all_agent_paths = FileHandler.get_all_agent_paths(project_dir_str)
            count = all_agent_paths.count(resolved_full_path)
            if count > 1:
                self.add_error(
                    f"Duplicate agent configuration file: "
                    f"{resolved_full_path} (found {count} times)."
                )
        except (OSError, ValueError, TypeError) as e:
            logger.exception("Error checking agent file uniqueness for %s: %s", full_path_str, e)
            self.add_error(f"Error checking agent file uniqueness for {full_path_str}: {e}")

    def _collect_agent_config_files(self, project_dir_str: str) -> Dict[str, List[str]]:
        """
        Collect all agent config files in the project.

        Returns:
            Dict mapping agent name (lowercase) to list of file paths
        """
        name_locations: Dict[str, List[str]] = {}
        for root, dirs, _ in os.walk(project_dir_str):
            if "agent_config" not in dirs:
                continue
            agent_cfg_dir = Path(root) / "agent_config"
            if not agent_cfg_dir.is_dir():
                continue
            self._scan_config_directory(agent_cfg_dir, name_locations)
        return name_locations

    def _scan_config_directory(
        self, agent_cfg_dir: Path, name_locations: Dict[str, List[str]]
    ) -> None:
        """Scan a config directory for agent YAML files."""
        for ext_pattern in ("*.yaml", "*.yml"):
            for file_obj in agent_cfg_dir.glob(ext_pattern):
                key = file_obj.stem.lower()
                name_locations.setdefault(key, []).append(str(file_obj.resolve()))

    def _check_agent_name_unique_logic(
        self,
        agent_name_to_check: str,
        project_dir_str: str,
        current_file_path_str: Optional[str] = None,
    ) -> None:
        """Check that agent name is unique in the project."""
        try:
            name_locations = self._collect_agent_config_files(project_dir_str)
            resolved_current_file_path = (
                str(Path(current_file_path_str).resolve()) if current_file_path_str else None
            )
            conflicts = name_locations.get(agent_name_to_check.lower(), [])
            if resolved_current_file_path:
                conflicts = [p for p in conflicts if p != resolved_current_file_path]
            if conflicts:
                self.add_error(
                    f"Agent name '{agent_name_to_check}' is not unique. "
                    f"Also defined in: {', '.join(conflicts)}."
                )
        except (OSError, ValueError, TypeError) as e:
            logger.exception(
                "Error checking agent name uniqueness for '%s': %s", agent_name_to_check, e
            )
            self.add_error(f"Error checking agent name uniqueness for '{agent_name_to_check}': {e}")

    def _validate_single_agent_entry_logic(
        self, entry: Dict[str, Any], cfg_ctx_name: str, proj_root: Optional[Path] = None
    ) -> None:
        """
        Validate a single agent entry using the orchestrator.

        This method delegates to AgentEntryValidationOrchestrator which runs
        a chain of specialized validators. This reduces complexity from
        CC 52 to ~5.

        Args:
            entry: Agent configuration entry to validate
            cfg_ctx_name: Context name for error messages
            proj_root: Optional project root for path resolution
        """
        orchestrator = AgentEntryValidationOrchestrator()
        orchestrator.validate_agent_entry(entry, cfg_ctx_name, proj_root)

        for error in orchestrator.get_validation_errors():
            self.add_error(error)

        for warning in orchestrator.get_validation_warnings():
            self.add_warning(warning)

    def _parse_properties_dict(self, properties_part: str) -> Optional[Dict[str, Any]]:
        """Parse properties part of array[object:...] type."""
        try:
            return json.loads(properties_part)
        except (ValueError, json.JSONDecodeError):
            try:
                return ast.literal_eval(properties_part)
            except (ValueError, SyntaxError):
                return None

    def _validate_property_type(self, prop_type: str) -> bool:
        """Validate a single property type."""
        if not isinstance(prop_type, str):
            return False
        cleaned_type = prop_type.replace("\\", "")
        base_type = cleaned_type[:-1] if cleaned_type.endswith("!") else cleaned_type
        valid_prop_types = {"string", "number", "integer", "boolean", "object"}
        return base_type in valid_prop_types

    def _is_valid_schema_type(
        self, type_str: str, valid_types: set, valid_array_types: set
    ) -> bool:
        """
        Check if a schema type string is valid, including complex object notation.

        Args:
            type_str: The type string to validate
            valid_types: Set of valid basic types
            valid_array_types: Set of valid array types

        Returns:
            bool: True if the type is valid, False otherwise
        """
        if type_str in valid_types or type_str in valid_array_types:
            return True
        if not (type_str.startswith("array[object:") and type_str.endswith("]")):
            return False
        properties_dict = self._parse_properties_dict(type_str[13:-1])
        if not isinstance(properties_dict, dict):
            return False
        for prop_name, prop_type in properties_dict.items():
            if not isinstance(prop_name, str):
                return False
            if not self._validate_property_type(prop_type):
                return False
        return True

    def _validate_agent_entries_list_logic(
        self, agent_cfg_list: Any, agent_name_ctx: str, proj_root: Optional[Path] = None
    ) -> None:
        """Validate a list of agent entries."""
        if not isinstance(agent_cfg_list, list):
            self.add_error(
                f"Agent configuration for '{agent_name_ctx}' must be a list, "
                f"but found {type(agent_cfg_list).__name__}."
            )
            return
        if not agent_cfg_list:
            self.add_warning(f"Agent configuration list for '{agent_name_ctx}' is empty.")
            return
        for entry in agent_cfg_list:
            self._validate_single_agent_entry_logic(entry, agent_name_ctx, proj_root)

    def _extract_dependencies_from_entry(self, entry: Dict[str, Any]) -> Set[str]:
        """Extract dependencies from an agent entry."""
        entry_ci = _ci_dict(entry) if isinstance(entry, dict) else {}
        deps: Set[str] = set()
        if isinstance(entry_ci.get("dependencies"), list):
            deps.update(dep.lower() for dep in entry_ci["dependencies"] if isinstance(dep, str))
        return deps

    def _validate_config_dependencies_logic(self, full_config_data: AgentConfigMap) -> None:
        """Validate dependencies in configuration."""
        available_agents = {name.lower() for name in full_config_data}
        for agent_name, entries in full_config_data.items():
            if not isinstance(entries, list):
                continue
            deps = set()
            for entry in entries:
                if isinstance(entry, dict):
                    deps.update(self._extract_dependencies_from_entry(entry))
            missing = deps - available_agents
            if missing:
                self.add_error(
                    f"Agent '{agent_name}' has missing dependencies: {', '.join(sorted(missing))}."
                )

    def _build_agent_sets(
        self, agent_cfgs_map: Dict[str, Dict[str, Any]]
    ) -> tuple[Set[str], Set[str]]:
        """Build sets of active and all agent names (lowercased).

        Returns:
            Tuple of (active_agents, all_agents) sets.
        """
        active_agents = {
            name.lower()
            for name, cfg in agent_cfgs_map.items()
            if isinstance(cfg, dict) and _ci_dict(cfg).get("is_operational", True)
        }
        all_agents = {name.lower() for name in agent_cfgs_map}
        return active_agents, all_agents

    def _validate_single_dependency(
        self,
        agent_name: str,
        dep: Any,
        all_agents: Set[str],
        active_agents: Set[str],
        agent_cfgs_map: Dict[str, Dict[str, Any]],
    ) -> None:
        """Validate a single dependency for an agent."""
        if not isinstance(dep, str):
            self.add_error(f"Agent '{agent_name}' has a non-string dependency: {dep}.")
            return
        dep_lc = dep.lower()
        if dep_lc not in all_agents:
            self.add_error(f"Active agent '{agent_name}' depends on a non-existent agent '{dep}'.")
        elif dep_lc not in active_agents:
            dep_cfg_ci = _ci_dict(agent_cfgs_map.get(dep, {}))
            if not dep_cfg_ci.get("is_operational", True):
                self.add_error(f"Active agent '{agent_name}' depends on an inactive agent '{dep}'.")

    def _validate_agent_dependencies(
        self,
        agent_name: str,
        cfg: Dict[str, Any],
        all_agents: Set[str],
        active_agents: Set[str],
        agent_cfgs_map: Dict[str, Dict[str, Any]],
    ) -> None:
        """Validate all dependencies for a single agent."""
        cfg_ci = _ci_dict(cfg) if isinstance(cfg, dict) else {}
        if not cfg_ci.get("is_operational", True):
            return
        deps = cfg_ci.get("dependencies", [])
        if not isinstance(deps, list):
            self.add_error(f"Agent '{agent_name}' has a 'dependencies' field that is not a list.")
            return
        for dep in deps:
            self._validate_single_dependency(
                agent_name, dep, all_agents, active_agents, agent_cfgs_map
            )

    def _validate_operational_dependencies_logic(
        self, agent_cfgs_map: Dict[str, Dict[str, Any]]
    ) -> None:
        """Validate operational dependencies."""
        active_agents, all_agents = self._build_agent_sets(agent_cfgs_map)
        for agent_name, cfg in agent_cfgs_map.items():
            self._validate_agent_dependencies(
                agent_name, cfg, all_agents, active_agents, agent_cfgs_map
            )

    def _check_circular_dependencies_logic(self, full_config_data: AgentConfigMap) -> None:
        """Check for circular dependencies in agent configuration."""
        graph: Dict[str, List[str]] = {}
        for agent_name, entries in full_config_data.items():
            if not isinstance(entries, list):
                continue
            deps = set()
            for entry in entries:
                if isinstance(entry, dict):
                    deps.update(self._extract_dependencies_from_entry(entry))
            graph[agent_name.lower()] = list(deps)
        visited: Set[str] = set()
        stack: List[str] = []

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
                    self.add_error(f"Circular dependency detected: {cycle}.")
                    return True
            stack.pop()
            return False

        for n in list(graph):
            if n not in visited:
                dfs(n)

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """Run validation based on the operation key in data."""
        self.clear_errors()
        self.clear_warnings()
        if not isinstance(data, dict):
            self.add_error("Validation input 'data' must be a dictionary.")
            return False
        operation = data.get("operation")
        if not operation:
            self.add_error("An 'operation' must be specified in the input 'data'.")
            return False
        proj_dir = data.get("project_dir")
        project_root_path = Path(proj_dir).resolve() if isinstance(proj_dir, (str, Path)) else None
        operation_map = {
            "validate_agent_config_file_meta": self._validate_agent_config_file_meta_operation,
            "validate_agent_entries": self._validate_agent_entries_operation,
        }
        handler = operation_map.get(operation)
        if handler is None:
            self.add_error(f"Unknown operation: {operation}")
        else:
            handler(data, project_root_path)
        return not self.has_errors()

    def _validate_agent_config_file_meta_operation(
        self, data: Dict[str, Any], project_root_path: Optional[Path]
    ) -> None:
        """Validate agent config file metadata."""
        cfg_path = data.get("config_path")
        agent_name = data.get(
            "agent_name", Path(cfg_path).stem if isinstance(cfg_path, str) else None
        )
        if not (isinstance(cfg_path, str) and isinstance(agent_name, str) and project_root_path):
            self.add_error(
                "For 'validate_agent_config_file_meta', provide "
                "'config_path' (str), 'agent_name' (str), and 'project_dir'."
            )
            return
        cfg_file = Path(cfg_path)
        if not self._ensure_path_exists(cfg_file):
            self.add_error(f"Config file does not exist: {cfg_file}")
        elif not self._is_file(cfg_file):
            self.add_error(f"Config path is not a file: {cfg_file}")
        elif not os.access(cfg_file, os.R_OK):
            self.add_error(f"Config file not readable: {cfg_file}")
        else:
            self._check_agent_file_unique_logic(str(cfg_file.resolve()), str(project_root_path))
            self._check_agent_name_unique_logic(
                agent_name, str(project_root_path), str(cfg_file.resolve())
            )

    def _validate_agent_entries_operation(
        self, data: Dict[str, Any], project_root_path: Optional[Path]
    ) -> None:
        """Validate agent entries operation."""
        cfg_list = data.get("agent_config_data")
        ctx_name = data.get("agent_name_context")
        if cfg_list is None or not isinstance(ctx_name, str):
            self.add_error(
                "For 'validate_agent_entries', provide "
                "'agent_config_data' and 'agent_name_context'."
            )
            return
        self._validate_agent_entries_list_logic(cfg_list, ctx_name, project_root_path)
