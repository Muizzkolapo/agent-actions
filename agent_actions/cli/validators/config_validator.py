# agent_actions/cli/validators/config_validator.py
import os
import glob
# Removed logging import from here as ConfigValidator itself won't log directly
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set, Union

from agent_actions.handlers.file_handler import FileHandler
from .base_validator import BaseValidator

# --- 2. Refactored ConfigValidator Class (Logging Removed) ---
class ConfigValidator(BaseValidator):
    """
    Handles various configuration validation operations.
    Internal logging via ServiceLogger has been removed from this version.
    """

    _REQUIRED_AGENT_KEYS: Set[str] = {'agent_type', 'model_name'}
    # Added 'granularity', 'side_collection', 'remove_collection' to optional keys
    # Also added 'model_vendor', 'model_name', 'json_mode', 'prompt_debug', 'api_key', 'prompt', 'schema_name', 'tools'
    # based on their usage in agent_config throughout the codebase.
    _OPTIONAL_AGENT_KEYS: Set[str] = {
        'description', 'version', 'author', 'dependencies', 'imports', 'config', 'parent',
        'granularity', 'side_collection', 'remove_collection', 'model_vendor',
        'json_mode', 'prompt_debug', 'api_key', 'prompt', 'schema_name', 'tools',
        'chunk_config', 'use_few_shot_samples', 'conditional_clause', 'is_operational', # Added more common optional keys
        'ephemeral' # from agent_workflow.py
    }
    _AGENT_TYPE_REQUIRED_KEYS: Dict[str, Set[str]] = {
        'llm': {'model_name'}, # Changed 'model' to 'model_name' for consistency with how it's often used
        'function': {'code_path'},
        # For 'tool', 'model_name' is used as the UDF identifier by ToolHandler.
        # 'api_key' might not always be required for a local tool/UDF.
        'tool': {'model_name'},
    }

    def _check_agent_file_unique_logic(self, full_path_str: str, project_dir_str: str) -> None:
        try:
            resolved_full_path = str(Path(full_path_str).resolve())
            all_agent_paths = FileHandler.get_all_agent_paths(project_dir_str)
            count = all_agent_paths.count(resolved_full_path)
            if count > 1:
                self.add_error(f"Duplicate agent configuration file: {resolved_full_path} (found {count} times).")
        except Exception as e:
            self.add_error(f"Error checking agent file uniqueness for {full_path_str}: {e}")

    def _check_agent_name_unique_logic(self, agent_name_to_check: str, project_dir_str: str, current_file_path_str: Optional[str] = None) -> None:
        try:
            name_locations: Dict[str, List[str]] = {}
            resolved_current_file_path = str(Path(current_file_path_str).resolve()) if current_file_path_str else None

            for root, dirs, _ in os.walk(project_dir_str):
                if "agent_config" in dirs:
                    agent_cfg_dir = Path(root) / "agent_config"
                    if agent_cfg_dir.is_dir():
                        for ext_pattern in ("*.yaml", "*.yml"):
                            for file_obj in agent_cfg_dir.glob(ext_pattern):
                                name_from_file_stem = file_obj.stem
                                resolved_path = str(file_obj.resolve())
                                if name_from_file_stem not in name_locations: name_locations[name_from_file_stem] = []
                                if resolved_path not in name_locations[name_from_file_stem]:
                                    name_locations[name_from_file_stem].append(resolved_path)
            
            conflicting_paths = name_locations.get(agent_name_to_check, [])
            if resolved_current_file_path:
                conflicting_paths = [p for p in conflicting_paths if p != resolved_current_file_path]

            if conflicting_paths:
                self.add_error(f"Agent name '{agent_name_to_check}' is not unique. Also defined in: {', '.join(conflicting_paths)}.")
        except Exception as e:
            self.add_error(f"Error checking agent name uniqueness for '{agent_name_to_check}': {e}")

    def _validate_single_agent_entry_logic(self, entry: Dict[str, Any], entry_idx: int, cfg_ctx_name: str, proj_root: Optional[Path] = None) -> None:
        desc = f"agent entry (index {entry_idx}) in '{cfg_ctx_name}'"
        if not isinstance(entry, dict):
            self.add_error(f"{desc} is not a dictionary.")
            return

        missing_req = self._REQUIRED_AGENT_KEYS - entry.keys()
        if missing_req: self.add_error(f"{desc} missing required key(s): {', '.join(missing_req)}.")
        
        name = entry.get('name')
        agent_type = entry.get('agent_type', '').lower() # Ensure agent_type is lower for comparisons
        model_vendor = entry.get('model_vendor', '').lower() # Get model_vendor, default to empty string and lower
        granularity = entry.get('granularity', 'record').lower() # Default to 'record' if not present

        if 'name' in entry and not isinstance(name, str): self.add_error(f"{desc} 'name' must be string.")
        
        if 'agent_type' in entry:
            if not isinstance(entry.get('agent_type'), str): self.add_error(f"{desc} 'agent_type' must be string.")
            elif agent_type in self._AGENT_TYPE_REQUIRED_KEYS:
                missing_type_specific = self._AGENT_TYPE_REQUIRED_KEYS[agent_type] - entry.keys()
                if missing_type_specific: self.add_error(f"{desc} (type '{agent_type}') missing type-specific key(s): {', '.join(missing_type_specific)}.")
            
            if agent_type == 'function' and 'code_path' in entry:
                cp_val = entry['code_path']
                if not isinstance(cp_val, str): self.add_error(f"{desc} 'code_path' for function agent must be a string.")
                elif proj_root and not cp_val.startswith(('http://', 'https://')): # Check if it's not a URL
                    abs_cp = Path(cp_val) if Path(cp_val).is_absolute() else proj_root / cp_val
                    if not self._ensure_path_exists(abs_cp): self.add_error(f"{desc} 'code_path' ({abs_cp}) does not exist.")
                    elif not self._is_file(abs_cp): self.add_error(f"{desc} 'code_path' ({abs_cp}) is not a file.")
        
        # New validation for tool vendor with file granularity
        if model_vendor == 'tool' and granularity == 'file':
            if 'side_collection' in entry: # Check for the key's presence
                self.add_error(
                    f"{desc} (model_vendor: 'tool', granularity: 'file') cannot have 'side_collection' defined. "
                    "This key should be removed for this agent configuration as file-level tools process content wholesale, "
                    "and side_collection is for record-level context enrichment."
                )
            if 'remove_collection' in entry: # Check for the key's presence
                self.add_error(
                    f"{desc} (model_vendor: 'tool', granularity: 'file') cannot have 'remove_collection' defined. "
                    "This key should be removed for this agent configuration as file-level tools process content wholesale, "
                    "and remove_collection is for modifying record-level context."
                )

        # Consolidate all known keys for the "unknown keys" check
        all_known_keys = self._REQUIRED_AGENT_KEYS.union(self._OPTIONAL_AGENT_KEYS)
        if agent_type in self._AGENT_TYPE_REQUIRED_KEYS:
            all_known_keys = all_known_keys.union(self._AGENT_TYPE_REQUIRED_KEYS[agent_type])
        
        # Special handling for 'config' key which can have arbitrary sub-keys
        keys_to_check_for_unknown = {k for k in entry.keys() if k != 'config'} 
        unknown_keys = keys_to_check_for_unknown - all_known_keys
        
        if unknown_keys: self.add_warning(f"{desc} has unknown key(s): {', '.join(unknown_keys)}. Ensure these are intended or correct typos.")
        
        if 'description' in entry and not isinstance(entry['description'], str): self.add_error(f"{desc} 'description' should be a string.")
        if 'version' in entry and not isinstance(entry['version'], (str, int, float)): self.add_error(f"{desc} 'version' should be a string or number.")
        if 'dependencies' in entry and not isinstance(entry['dependencies'], list): self.add_error(f"{desc} 'dependencies' should be a list.")
        if 'is_operational' in entry and not isinstance(entry['is_operational'], bool): self.add_error(f"{desc} 'is_operational' should be a boolean.")
        if 'json_mode' in entry and not isinstance(entry['json_mode'], bool): self.add_error(f"{desc} 'json_mode' should be a boolean.")
        if 'prompt_debug' in entry and not isinstance(entry['prompt_debug'], bool): self.add_error(f"{desc} 'prompt_debug' should be a boolean.")
        if 'granularity' in entry and entry['granularity'] not in ['record', 'file']: self.add_error(f"{desc} 'granularity' must be 'record' or 'file'.")


    def _validate_agent_entries_list_logic(self, agent_cfg_list: Any, agent_name_ctx: str, proj_root: Optional[Path] = None) -> None:
        if not isinstance(agent_cfg_list, list):
            self.add_error(f"Agent configuration for '{agent_name_ctx}' must be a list, but found type {type(agent_cfg_list).__name__}.")
            return
        if not agent_cfg_list:
            self.add_warning(f"Agent configuration list for '{agent_name_ctx}' is empty.")
            return
        for i, entry in enumerate(agent_cfg_list):
            self._validate_single_agent_entry_logic(entry, i, agent_name_ctx, proj_root)

    def _extract_dependencies_from_entry(self, entry: Dict[str, Any]) -> Set[str]:
        dependencies: Set[str] = set()
        if isinstance(entry.get('dependencies'), list):
            dependencies.update(dep for dep in entry['dependencies'] if isinstance(dep, str))
        return dependencies

    def _validate_config_dependencies_logic(self, full_config_data: Dict[str, List[Dict[str, Any]]]) -> None:
        available_agents = set(full_config_data.keys())
        for agent_name, agent_entries_list in full_config_data.items():
            if not isinstance(agent_entries_list, list): continue
            all_dependencies_for_agent: Set[str] = set()
            for entry in agent_entries_list:
                if isinstance(entry, dict):
                    all_dependencies_for_agent.update(self._extract_dependencies_from_entry(entry))
            missing_deps = all_dependencies_for_agent - available_agents
            if missing_deps:
                self.add_error(f"Agent '{agent_name}' has missing dependencies: {', '.join(missing_deps)}.")

    def _validate_operational_dependencies_logic(self, agent_configs_map: Dict[str, Dict[str, Any]]) -> None:
        active_agents = {name for name, cfg in agent_configs_map.items() if isinstance(cfg, dict) and cfg.get('is_operational', True)}
        all_defined_agents = set(agent_configs_map.keys())

        for agent_name, agent_cfg in agent_configs_map.items():
            if not (isinstance(agent_cfg, dict) and agent_cfg.get('is_operational', True)): continue
            dependencies = agent_cfg.get('dependencies', [])
            if not isinstance(dependencies, list):
                self.add_error(f"Agent '{agent_name}' has a 'dependencies' field that is not a list.")
                continue
            for dep_name in dependencies:
                if not isinstance(dep_name, str):
                    self.add_error(f"Agent '{agent_name}' has a non-string dependency: {dep_name}.")
                    continue
                if dep_name not in all_defined_agents:
                    self.add_error(f"Active agent '{agent_name}' depends on a non-existent agent '{dep_name}'.")
                elif dep_name not in active_agents:
                    dep_cfg_details = agent_configs_map.get(dep_name) # Check if this dependency is explicitly inactive
                    if isinstance(dep_cfg_details, dict) and not dep_cfg_details.get('is_operational', True):
                         self.add_error(f"Active agent '{agent_name}' depends on an inactive agent '{dep_name}'.")

    def _check_circular_dependencies_logic(self, full_config_data: Dict[str, List[Dict[str, Any]]]) -> None:
        graph: Dict[str, List[str]] = {}
        for agent_name, agent_entries_list in full_config_data.items():
            if not isinstance(agent_entries_list, list): continue
            current_agent_deps: Set[str] = set()
            for entry in agent_entries_list:
                 if isinstance(entry, dict):
                    current_agent_deps.update(self._extract_dependencies_from_entry(entry))
            graph[agent_name] = list(current_agent_deps)

        visited_nodes: Set[str] = set()
        recursion_path: List[str] = []
        def dfs_has_cycle(node: str) -> bool:
            visited_nodes.add(node)
            recursion_path.append(node)
            for neighbor in graph.get(node, []):
                if neighbor not in visited_nodes:
                    if dfs_has_cycle(neighbor): return True
                elif neighbor in recursion_path:
                    try:
                        cycle_start_index = recursion_path.index(neighbor)
                        cycle_str = " -> ".join(recursion_path[cycle_start_index:] + [neighbor])
                        self.add_error(f"Circular dependency detected: {cycle_str}.")
                    except ValueError:
                        self.add_error(f"Circular dependency involving {neighbor} (path reconstruction error).")
                    return True
            recursion_path.pop()
            return False
        for node_name in list(graph.keys()): # Use list(graph.keys()) if graph might be modified during iteration (not here, but good practice)
            if node_name not in visited_nodes:
                if dfs_has_cycle(node_name):
                    # Cycle found and error added, clear path for next DFS if needed
                    recursion_path.clear() # Important if DFS is re-entrant for multiple components

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        self.clear_errors()
        self.clear_warnings()

        if not isinstance(data, dict):
            self.add_error("Validation input 'data' must be a dictionary.")
            return False
        operation = data.get("operation")
        if not operation:
            self.add_error("An 'operation' must be specified in the input 'data'.")
            return False

        # Logging for operation start (if desired) would be done by the CALLER now.
        # Example: logger.info(f"ConfigValidator starting operation: {operation}")

        proj_dir = data.get("project_dir")
        project_root_path = Path(proj_dir).resolve() if isinstance(proj_dir, (str, Path)) else None
        
        operation_performed_successfully = True # Assume success unless an unknown operation is hit

        if operation == "validate_agent_config_file_meta":
            cfg_path_str = data.get("config_path")
            agent_name_str = data.get("agent_name", Path(cfg_path_str).stem if isinstance(cfg_path_str, str) else None)
            if not (isinstance(cfg_path_str, str) and isinstance(agent_name_str, str) and project_root_path):
                self.add_error("For 'validate_agent_config_file_meta', provide 'config_path' (str), 'agent_name' (str), and 'project_dir' (str/Path).")
            else:
                cfg_file = Path(cfg_path_str)
                if not self._ensure_path_exists(cfg_file): self.add_error(f"Config file does not exist: {cfg_file}")
                elif not self._is_file(cfg_file): self.add_error(f"Config path is not a file: {cfg_file}")
                elif not os.access(cfg_file, os.R_OK): self.add_error(f"Config file not readable: {cfg_file}") # os.access is fine
                else:
                    self._check_agent_file_unique_logic(str(cfg_file.resolve()), str(project_root_path))
                    self._check_agent_name_unique_logic(agent_name_str, str(project_root_path), str(cfg_file.resolve()))
        
        elif operation == "validate_agent_entries":
            agent_cfg_data = data.get("agent_config_data")
            agent_name_context = data.get("agent_name_context") # Renamed for clarity from agent_name
            if agent_cfg_data is None or not isinstance(agent_name_context, str): # Check agent_cfg_data is not None
                self.add_error("For 'validate_agent_entries', provide 'agent_config_data' and 'agent_name_context' (str).")
            else:
                self._validate_agent_entries_list_logic(agent_cfg_data, agent_name_context, project_root_path)

        elif operation == "validate_agent_in_full_config":
            full_cfg_data = data.get("full_config_data")
            agent_to_validate = data.get("agent_name")
            if not (isinstance(full_cfg_data, dict) and isinstance(agent_to_validate, str)):
                self.add_error("For 'validate_agent_in_full_config', provide 'full_config_data' (dict) and 'agent_name' (str).")
            elif agent_to_validate not in full_cfg_data:
                self.add_error(f"Agent '{agent_to_validate}' not found in the provided full configuration.")
            else:
                self._validate_agent_entries_list_logic(full_cfg_data[agent_to_validate], agent_to_validate, project_root_path)

        elif operation == "validate_config_dependencies":
            full_cfg_data = data.get("full_config_data")
            if not isinstance(full_cfg_data, dict): self.add_error("For 'validate_config_dependencies', 'full_config_data' (dict) is required.")
            else: self._validate_config_dependencies_logic(full_cfg_data)
        
        elif operation == "validate_operational_dependencies":
            agent_cfgs_map = data.get("agent_configs_map")
            if not isinstance(agent_cfgs_map, dict): self.add_error("For 'validate_operational_dependencies', 'agent_configs_map' (dict) is required.")
            else: self._validate_operational_dependencies_logic(agent_cfgs_map)

        elif operation == "check_circular_dependencies":
            full_cfg_data = data.get("full_config_data")
            if not isinstance(full_cfg_data, dict): self.add_error("For 'check_circular_dependencies', 'full_config_data' (dict) is required.")
            else: self._check_circular_dependencies_logic(full_cfg_data)
        
        elif operation == "ensure_config_is_list":
            cfg_payload = data.get("config_payload")
            cfg_desc = data.get("config_description", "The configuration") # Default description
            if not isinstance(cfg_payload, list):
                self.add_error(f"{cfg_desc} must be a list, but found type {type(cfg_payload).__name__}.")
        else:
            self.add_error(f"Unknown ConfigValidator operation specified: '{operation}'.")
            operation_performed_successfully = False # Operation itself was unknown

        # Logging for operation end (if desired) would be done by the CALLER now.
        # Example: 
        # if self.has_errors() or not operation_performed_successfully:
        #     logger.error(f"ConfigValidator operation '{operation}' failed: {self.get_errors()}")
        # else:
        #     logger.info(f"ConfigValidator operation '{operation}' completed successfully.")
            
        return not self.has_errors() and operation_performed_successfully
