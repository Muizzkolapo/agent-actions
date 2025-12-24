import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from agent_actions.response_processing.config_types import AgentConfigMap
from agent_actions.io.file_handler import FileHandler
from agent_actions.validation.base_validator import BaseValidator
from agent_actions.utilities.constants import MODEL_VENDOR_KEY, MODEL_NAME_KEY, JSON_MODE_KEY, API_KEY_KEY, PROMPT_KEY, SCHEMA_NAME_KEY, SCHEMA_KEY, CHUNK_CONFIG_KEY
from agent_actions.validation.orchestration.agent_entry_validation_orchestrator import AgentEntryValidationOrchestrator

class ConfigValidator(BaseValidator):
    """Validate agent‑configuration files with **case‑insensitive** key handling.

    Business rules are unchanged; only comparisons are agnostic to key‑case or value‑case.
    """
    _REQUIRED_AGENT_KEYS: Set[str] = {'agent_type', MODEL_NAME_KEY}
    _OPTIONAL_AGENT_KEYS: Set[str] = {'description', 'version', 'author', 'dependencies', 'imports', 'config', 'granularity', MODEL_VENDOR_KEY, JSON_MODE_KEY, 'prompt_debug', API_KEY_KEY, PROMPT_KEY, SCHEMA_NAME_KEY, SCHEMA_KEY, 'tools', CHUNK_CONFIG_KEY, 'few_shot', 'conditional_clause', 'is_operational', 'ephemeral', 'add_dispatch', 'output_field', 'context_scope'}
    _AGENT_TYPE_REQUIRED_KEYS: Dict[str, Set[str]] = {'llm': {MODEL_NAME_KEY}, 'function': {'code_path'}, 'tool': {MODEL_NAME_KEY}}

    @staticmethod
    def _ci_dict(d: Dict[str, Any]) -> Dict[str, Any]:
        """Return a **new** dict with **lower‑case keys** for CI look‑ups."""
        return {str(k).lower(): v for k, v in d.items()}

    @staticmethod
    def _ci_get(d: Dict[str, Any], key: str, default: Any=None) -> Any:
        """Case‑insensitive ``dict`` ``get``."""
        for k, v in d.items():
            if str(k).lower() == key.lower():
                return v
        return default

    def _check_agent_file_unique_logic(self, full_path_str: str, project_dir_str: str) -> None:
        try:
            resolved_full_path = str(Path(full_path_str).resolve())
            all_agent_paths = FileHandler.get_all_agent_paths(project_dir_str)
            if all_agent_paths.count(resolved_full_path) > 1:
                self.add_error(f'Duplicate agent configuration file: {resolved_full_path} (found {all_agent_paths.count(resolved_full_path)} times).')
        except Exception as e:
            logger.exception(
                f"Error checking agent file uniqueness for {full_path_str}: {e}"
            )
            self.add_error(f'Error checking agent file uniqueness for {full_path_str}: {e}')

    def _check_agent_name_unique_logic(self, agent_name_to_check: str, project_dir_str: str, current_file_path_str: Optional[str]=None) -> None:
        try:
            name_locations: Dict[str, List[str]] = {}
            resolved_current_file_path = str(Path(current_file_path_str).resolve()) if current_file_path_str else None
            for root, dirs, _ in os.walk(project_dir_str):
                if 'agent_config' in dirs:
                    agent_cfg_dir = Path(root) / 'agent_config'
                    if agent_cfg_dir.is_dir():
                        for ext_pattern in ('*.yaml', '*.yml'):
                            for file_obj in agent_cfg_dir.glob(ext_pattern):
                                key = file_obj.stem.lower()
                                name_locations.setdefault(key, []).append(str(file_obj.resolve()))
            conflicts = name_locations.get(agent_name_to_check.lower(), [])
            if resolved_current_file_path:
                conflicts = [p for p in conflicts if p != resolved_current_file_path]
            if conflicts:
                self.add_error(f"Agent name '{agent_name_to_check}' is not unique. Also defined in: {', '.join(conflicts)}.")
        except Exception as e:
            logger.exception(
                f"Error checking agent name uniqueness for '{agent_name_to_check}': {e}"
            )
            self.add_error(f"Error checking agent name uniqueness for '{agent_name_to_check}': {e}")

    def _validate_single_agent_entry_logic(self, entry: Dict[str, Any], cfg_ctx_name: str, proj_root: Optional[Path]=None) -> None:
        """
        Validate a single agent entry using the orchestrator.

        This method now delegates to AgentEntryValidationOrchestrator which runs
        a chain of specialized validators. This reduces complexity from CC 52 to ~5.

        Args:
            entry: Agent configuration entry to validate
            cfg_ctx_name: Context name for error messages
            proj_root: Optional project root for path resolution
        """
        # Create orchestrator and run validation chain
        orchestrator = AgentEntryValidationOrchestrator()
        orchestrator.validate_agent_entry(entry, cfg_ctx_name, proj_root)

        # Collect errors and warnings from orchestrator
        for error in orchestrator.get_validation_errors():
            self.add_error(error)

        for warning in orchestrator.get_validation_warnings():
            self.add_warning(warning)

    def _is_valid_schema_type(self, type_str: str, valid_types: set, valid_array_types: set) -> bool:
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
        if type_str.startswith('array[object:') and type_str.endswith(']'):
            properties_part = type_str[13:-1]
            import ast
            import json
            try:
                try:
                    properties_dict = json.loads(properties_part)
                except (ValueError, json.JSONDecodeError):
                    properties_dict = ast.literal_eval(properties_part)
                if isinstance(properties_dict, dict):
                    for prop_name, prop_type in properties_dict.items():
                        if not isinstance(prop_name, str):
                            return False
                        if not isinstance(prop_type, str):
                            return False
                        cleaned_type = prop_type.replace('\\', '')
                        if cleaned_type.endswith('!'):
                            base_prop_type = cleaned_type[:-1]
                        else:
                            base_prop_type = cleaned_type
                        valid_prop_types = {'string', 'number', 'integer', 'boolean', 'object'}
                        if base_prop_type not in valid_prop_types:
                            return False
                    return True
                else:
                    return False
            except (ValueError, SyntaxError, json.JSONDecodeError):
                return False
        return False

    def _validate_agent_entries_list_logic(self, agent_cfg_list: Any, agent_name_ctx: str, proj_root: Optional[Path]=None) -> None:
        if not isinstance(agent_cfg_list, list):
            self.add_error(f"Agent configuration for '{agent_name_ctx}' must be a list, but found {type(agent_cfg_list).__name__}.")
            return
        if not agent_cfg_list:
            self.add_warning(f"Agent configuration list for '{agent_name_ctx}' is empty.")
            return
        for entry in agent_cfg_list:
            self._validate_single_agent_entry_logic(entry, agent_name_ctx, proj_root)

    def _extract_dependencies_from_entry(self, entry: Dict[str, Any]) -> Set[str]:
        entry_ci = self._ci_dict(entry) if isinstance(entry, dict) else {}
        deps: Set[str] = set()
        if isinstance(entry_ci.get('dependencies'), list):
            deps.update((dep.lower() for dep in entry_ci['dependencies'] if isinstance(dep, str)))
        return deps

    def _validate_config_dependencies_logic(self, full_config_data: AgentConfigMap) -> None:
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
                self.add_error(f"Agent '{agent_name}' has missing dependencies: {', '.join(sorted(missing))}.")

    def _validate_operational_dependencies_logic(self, agent_cfgs_map: Dict[str, Dict[str, Any]]) -> None:
        active_agents = {name.lower() for name, cfg in agent_cfgs_map.items() if isinstance(cfg, dict) and self._ci_dict(cfg).get('is_operational', True)}
        all_agents = {name.lower() for name in agent_cfgs_map}
        for agent_name, cfg in agent_cfgs_map.items():
            cfg_ci = self._ci_dict(cfg) if isinstance(cfg, dict) else {}
            if not cfg_ci.get('is_operational', True):
                continue
            deps = cfg_ci.get('dependencies', [])
            if not isinstance(deps, list):
                self.add_error(f"Agent '{agent_name}' has a 'dependencies' field that is not a list.")
                continue
            for dep in deps:
                if not isinstance(dep, str):
                    self.add_error(f"Agent '{agent_name}' has a non‑string dependency: {dep}.")
                    continue
                dep_lc = dep.lower()
                if dep_lc not in all_agents:
                    self.add_error(f"Active agent '{agent_name}' depends on a non‑existent agent '{dep}'.")
                elif dep_lc not in active_agents:
                    dep_cfg_ci = self._ci_dict(agent_cfgs_map.get(dep, {}))
                    if not dep_cfg_ci.get('is_operational', True):
                        self.add_error(f"Active agent '{agent_name}' depends on an inactive agent '{dep}'.")

    def _check_circular_dependencies_logic(self, full_config_data: AgentConfigMap) -> None:
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
                    cycle = ' -> '.join(stack[cycle_idx:] + [neighbor])
                    self.add_error(f'Circular dependency detected: {cycle}.')
                    return True
            stack.pop()
            return False
        for n in list(graph):
            if n not in visited:
                dfs(n)

    def validate(self, data: Any, config: Optional[Dict[str, Any]]=None) -> bool:
        """Run validation based on the *operation* key in ``data``."""
        self.clear_errors()
        self.clear_warnings()
        if not isinstance(data, dict):
            self.add_error("Validation input 'data' must be a dictionary.")
            return False
        operation = data.get('operation')
        if not operation:
            self.add_error("An 'operation' must be specified in the input 'data'.")
            return False
        proj_dir = data.get('project_dir')
        project_root_path = Path(proj_dir).resolve() if isinstance(proj_dir, (str, Path)) else None
        operation_map = {'validate_agent_config_file_meta': self._validate_agent_config_file_meta_operation, 'validate_agent_entries': self._validate_agent_entries_operation}
        handler = operation_map.get(operation)
        if handler is None:
            self.add_error(f'Unknown operation: {operation}')
        else:
            handler(data, project_root_path)
        return not self.has_errors()

    def _validate_agent_config_file_meta_operation(self, data: Dict[str, Any], project_root_path: Optional[Path]) -> None:
        cfg_path = data.get('config_path')
        agent_name = data.get('agent_name', Path(cfg_path).stem if isinstance(cfg_path, str) else None)
        if not (isinstance(cfg_path, str) and isinstance(agent_name, str) and project_root_path):
            self.add_error("For 'validate_agent_config_file_meta', provide 'config_path' (str), 'agent_name' (str), and 'project_dir'.")
            return
        cfg_file = Path(cfg_path)
        if not self._ensure_path_exists(cfg_file):
            self.add_error(f'Config file does not exist: {cfg_file}')
        elif not self._is_file(cfg_file):
            self.add_error(f'Config path is not a file: {cfg_file}')
        elif not os.access(cfg_file, os.R_OK):
            self.add_error(f'Config file not readable: {cfg_file}')
        else:
            self._check_agent_file_unique_logic(str(cfg_file.resolve()), str(project_root_path))
            self._check_agent_name_unique_logic(agent_name, str(project_root_path), str(cfg_file.resolve()))

    def _validate_agent_entries_operation(self, data: Dict[str, Any], project_root_path: Optional[Path]) -> None:
        cfg_list = data.get('agent_config_data')
        ctx_name = data.get('agent_name_context')
        if cfg_list is None or not isinstance(ctx_name, str):
            self.add_error("For 'validate_agent_entries', provide 'agent_config_data' and 'agent_name_context'.")
            return
        self._validate_agent_entries_list_logic(cfg_list, ctx_name, project_root_path)