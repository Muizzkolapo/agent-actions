import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from agent_actions.core.parser.config_types import AgentConfigMap

from agent_actions.agents.handlers.file_handler import FileHandler
from agent_actions.agents.base.base_validator import BaseValidator
from agent_actions.core.constants import (
    MODEL_VENDOR_KEY,
    MODEL_NAME_KEY,
    JSON_MODE_KEY,
    API_KEY_KEY,
    PROMPT_KEY,
    SCHEMA_NAME_KEY,
    SCHEMA_KEY,
    CHUNK_CONFIG_KEY,
    OBSERVE_KEY,
)

# ---------------------------------------------------------------------------------------------
# ConfigValidator (Case‑Insensitive Validation)
# ---------------------------------------------------------------------------------------------
class ConfigValidator(BaseValidator):
    """Validate agent‑configuration files with **case‑insensitive** key handling.

    Business rules are unchanged; only comparisons are agnostic to key‑case or value‑case.
    """

    # -----------------------------------------------------------------------------------------
    # CONSTANTS (stored lower‑case for cheap comparisons)
    # -----------------------------------------------------------------------------------------
    _REQUIRED_AGENT_KEYS: Set[str] = {"agent_type", MODEL_NAME_KEY}

    _OPTIONAL_AGENT_KEYS: Set[str] = {
        "description",
        "version",
        "author",
        "dependencies",
        "imports",
        "config",
        "parent",
        "granularity",
        OBSERVE_KEY,
        "drops",
        MODEL_VENDOR_KEY,
        JSON_MODE_KEY,
        "prompt_debug",
        API_KEY_KEY,
        PROMPT_KEY,
        SCHEMA_NAME_KEY,
        SCHEMA_KEY,
        "tools",
        CHUNK_CONFIG_KEY,
        "few_shot",
        "conditional_clause",
        "is_operational",
        "ephemeral",
        "add_dispatch",
        "output_field",
    }

    _AGENT_TYPE_REQUIRED_KEYS: Dict[str, Set[str]] = {
        "llm": {MODEL_NAME_KEY},
        "function": {"code_path"},
        "tool": {MODEL_NAME_KEY},
    }

    # -----------------------------------------------------------------------------------------
    # HELPER UTILITIES
    # -----------------------------------------------------------------------------------------
    @staticmethod
    def _ci_dict(d: Dict[str, Any]) -> Dict[str, Any]:
        """Return a **new** dict with **lower‑case keys** for CI look‑ups."""
        return {str(k).lower(): v for k, v in d.items()}

    @staticmethod
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case‑insensitive ``dict`` ``get``."""
        for k, v in d.items():
            if str(k).lower() == key.lower():
                return v
        return default

    # -----------------------------------------------------------------------------------------
    # DUPLICATE FILE / NAME CHECKS (unchanged)
    # -----------------------------------------------------------------------------------------
    def _check_agent_file_unique_logic(self, full_path_str: str, project_dir_str: str) -> None:
        try:
            resolved_full_path = str(Path(full_path_str).resolve())
            all_agent_paths = FileHandler.get_all_agent_paths(project_dir_str)
            if all_agent_paths.count(resolved_full_path) > 1:
                self.add_error(
                    f"Duplicate agent configuration file: {resolved_full_path} (found {all_agent_paths.count(resolved_full_path)} times)."
                )
        except Exception as e:
            self.add_error(f"Error checking agent file uniqueness for {full_path_str}: {e}")

    def _check_agent_name_unique_logic(
        self,
        agent_name_to_check: str,
        project_dir_str: str,
        current_file_path_str: Optional[str] = None,
    ) -> None:
        try:
            name_locations: Dict[str, List[str]] = {}
            resolved_current_file_path = (
                str(Path(current_file_path_str).resolve()) if current_file_path_str else None
            )

            for root, dirs, _ in os.walk(project_dir_str):
                if "agent_config" in dirs:
                    agent_cfg_dir = Path(root) / "agent_config"
                    if agent_cfg_dir.is_dir():
                        for ext_pattern in ("*.yaml", "*.yml"):
                            for file_obj in agent_cfg_dir.glob(ext_pattern):
                                key = file_obj.stem.lower()
                                name_locations.setdefault(key, []).append(str(file_obj.resolve()))

            conflicts = name_locations.get(agent_name_to_check.lower(), [])
            if resolved_current_file_path:
                conflicts = [p for p in conflicts if p != resolved_current_file_path]
            if conflicts:
                self.add_error(
                    f"Agent name '{agent_name_to_check}' is not unique. Also defined in: {', '.join(conflicts)}."
                )
        except Exception as e:
            self.add_error(f"Error checking agent name uniqueness for '{agent_name_to_check}': {e}")

    # -----------------------------------------------------------------------------------------
    # CORE VALIDATION OF A SINGLE ENTRY (CI logic lives here)
    # -----------------------------------------------------------------------------------------
    def _validate_single_agent_entry_logic(
        self,
        entry: Dict[str, Any],
        entry_idx: int,
        cfg_ctx_name: str,
        proj_root: Optional[Path] = None,
    ) -> None:
        desc = f"agent entry {entry['agent_type']} in '{cfg_ctx_name}'"
        if not isinstance(entry, dict):
            self.add_error(f"{desc} is not a dictionary.")
            return

        entry_ci = self._ci_dict(entry)

        # -------------------------- required keys -----------------------------------
        missing_req = self._REQUIRED_AGENT_KEYS - set(entry_ci)
        if missing_req:
            self.add_error(f"{desc} missing required key(s): {', '.join(missing_req)}.")

        # -------------------------- core fields (CI) --------------------------------
        name = entry_ci.get("name")
        agent_type = str(entry_ci.get("agent_type", "")).lower()
        model_vendor = str(entry_ci.get(MODEL_VENDOR_KEY, "")).lower()
        granularity_raw = entry_ci.get("granularity", "record")
        granularity = str(granularity_raw).lower()

        if "name" in entry_ci and not isinstance(name, str):
            self.add_error(f"{desc} 'name' must be string.")

        # -------------------------- agent‑type specific ------------------------------
        if "agent_type" in entry_ci:
            if not isinstance(self._ci_get(entry, "agent_type"), str):
                self.add_error(f"{desc} 'agent_type' must be string.")
            elif agent_type in self._AGENT_TYPE_REQUIRED_KEYS:
                missing_type_specific = {
                    k for k in self._AGENT_TYPE_REQUIRED_KEYS[agent_type] if k not in entry_ci
                }
                if missing_type_specific:
                    self.add_error(
                        f"{desc} (type '{agent_type}') missing type‑specific key(s): {', '.join(missing_type_specific)}."
                    )

            if agent_type == "function" and "code_path" in entry_ci:
                cp_val = entry_ci["code_path"]
                if not isinstance(cp_val, str):
                    self.add_error(f"{desc} 'code_path' for function agent must be a string.")
                elif proj_root and not cp_val.startswith(("http://", "https://")):
                    abs_cp = Path(cp_val) if Path(cp_val).is_absolute() else proj_root / cp_val
                    if not self._ensure_path_exists(abs_cp):
                        self.add_error(f"{desc} 'code_path' ({abs_cp}) does not exist.")
                    elif not self._is_file(abs_cp):
                        self.add_error(f"{desc} 'code_path' ({abs_cp}) is not a file.")

        # -------------------------- tool vendor w/ file granularity ------------------
        if model_vendor == "tool" and granularity == "file":
            if OBSERVE_KEY in entry_ci:
                self.add_error(
                    f"{desc} (model_vendor: 'tool', granularity: 'file') cannot have 'observe' defined. "
                    "This key should be removed for this agent configuration as file‑level tools process content wholesale, "
                    "and observe is for record‑level context enrichment."
                )
            if "drops" in entry_ci:
                self.add_error(
                    f"{desc} (model_vendor: 'tool', granularity: 'file') cannot have 'drops' defined. "
                    "This key should be removed for this agent configuration as file‑level tools process content wholesale, "
                    "and drops is for modifying record‑level context."
                )
        
        # -------------------------- batch mode validation -------------------------------
        run_mode = str(entry_ci.get("run_mode", "")).lower()
        if run_mode == "batch":
            # Validate model_vendor is compatible with batch processing
            valid_batch_vendors = {"openai", "gemini", "anthropic"}
            if model_vendor and model_vendor not in valid_batch_vendors:
                if model_vendor == "tool":
                    self.add_error(
                        f"{desc} 'tool' vendor does not support batch processing. "
                        f"Use one of: {', '.join(sorted(valid_batch_vendors))} for batch mode."
                    )
                else:
                    self.add_error(
                        f"{desc} model_vendor '{model_vendor}' is not supported for batch processing. "
                        f"Supported batch providers: {', '.join(sorted(valid_batch_vendors))}"
                    )
            
            # Check for deprecated batch_provider field
            batch_provider = entry_ci.get("batch_provider")
            if batch_provider and not model_vendor:
                self.add_warning(
                    f"{desc} 'batch_provider' is deprecated. Use 'model_vendor' instead. "
                    f"Found: batch_provider='{batch_provider}'"
                )

        # -------------------------- unknown keys (CI) --------------------------------
        all_known_keys = self._REQUIRED_AGENT_KEYS | self._OPTIONAL_AGENT_KEYS
        if agent_type in self._AGENT_TYPE_REQUIRED_KEYS:
            all_known_keys |= self._AGENT_TYPE_REQUIRED_KEYS[agent_type]

        keys_to_check = {k.lower() for k in entry if k.lower() != "config"}
        unknown_keys = keys_to_check - all_known_keys
        if unknown_keys:
            self.add_warning(
                f"{desc} has unknown key(s): {', '.join(sorted(unknown_keys))}. Ensure these are intended or correct typos."
            )

        # -------------------------- field‑type validations ---------------------------
        if "description" in entry_ci and not isinstance(entry_ci["description"], str):
            self.add_error(f"{desc} 'description' should be a string.")
        if "version" in entry_ci and not isinstance(entry_ci["version"], (str, int, float)):
            self.add_error(f"{desc} 'version' should be a string or number.")
        if "dependencies" in entry_ci and not isinstance(entry_ci["dependencies"], list):
            self.add_error(f"{desc} 'dependencies' should be a list.")
        if "is_operational" in entry_ci and not isinstance(entry_ci["is_operational"], bool):
            self.add_error(f"{desc} 'is_operational' should be a boolean.")
        if JSON_MODE_KEY in entry_ci and not isinstance(entry_ci[JSON_MODE_KEY], bool):
            self.add_error(f"{desc} 'json_mode' should be a boolean.")
        if "prompt_debug" in entry_ci and not isinstance(entry_ci["prompt_debug"], bool):
            self.add_error(f"{desc} 'prompt_debug' should be a boolean.")
        if "granularity" in entry_ci and granularity not in ["record", "file"]:
            self.add_error(f"{desc} 'granularity' must be 'record' or 'file'.")

        # -------------------------- output_field validation --------------------------
        if "output_field" in entry_ci and entry_ci.get(JSON_MODE_KEY, True):
            self.add_error(
                f"{desc} 'output_field' can only be used when 'json_mode' is false."
            )
        
        # -------------------------- inline schema validation --------------------------
        if SCHEMA_KEY in entry_ci:
            inline_schema = entry_ci[SCHEMA_KEY]
            if not isinstance(inline_schema, dict):
                self.add_error(f"{desc} 'schema' must be a dictionary with field names as keys and types as values.")
            else:
                # Validate that all values are valid types
                valid_types = {"string", "number", "integer", "boolean", "array", "object"}
                valid_array_types = {"array[string]", "array[number]", "array[integer]", "array[boolean]", "array[object]"}
                
                for field_name, field_type in inline_schema.items():
                    if not isinstance(field_name, str):
                        self.add_error(f"{desc} 'schema' keys must be strings, found {type(field_name).__name__}.")
                        continue
                    
                    if not isinstance(field_type, str):
                        self.add_error(f"{desc} 'schema' value for field '{field_name}' must be a string type, found {type(field_type).__name__}.")
                        continue
                    
                    # Remove ! suffix if present (for required fields)
                    base_type = field_type.rstrip("!")
                    
                    # Check if it's a valid type (including complex object notation)
                    if not self._is_valid_schema_type(base_type, valid_types, valid_array_types):
                        self.add_error(
                            f"{desc} 'schema' field '{field_name}' has invalid type '{base_type}'. "
                            f"Valid types are: {', '.join(sorted(valid_types | valid_array_types))} or array[object:{{'prop': 'type'}}]"
                        )
                
                # Check for conflicts with schema_name
                if SCHEMA_NAME_KEY in entry_ci:
                    self.add_warning(
                        f"{desc} has both 'schema' and 'schema_name' defined. "
                        "The inline 'schema' will take precedence over 'schema_name'."
                    )

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
        # Check basic types first
        if type_str in valid_types or type_str in valid_array_types:
            return True
        
        # Check for complex object notation: array[object:{'prop': 'type'}]
        if type_str.startswith("array[object:") and type_str.endswith("]"):
            # Extract the object properties part
            properties_part = type_str[13:-1]  # Remove "array[object:" and "]"
            
            # Try to validate the properties syntax
            import ast
            import json
            
            try:
                # Try to parse as JSON first (more common in config files), then Python literal
                try:
                    properties_dict = json.loads(properties_part)
                except (ValueError, json.JSONDecodeError):
                    properties_dict = ast.literal_eval(properties_part)
                
                # Validate that it's a dict and all values are valid types
                if isinstance(properties_dict, dict):
                    for prop_name, prop_type in properties_dict.items():
                        if not isinstance(prop_name, str):
                            return False
                        
                        # Ensure prop_type is a string and remove ! suffix for required field check
                        if not isinstance(prop_type, str):
                            return False
                        
                        # Handle escaped characters and remove trailing ! if present
                        cleaned_type = prop_type.replace("\\", "")  # Remove backslashes first
                        if cleaned_type.endswith("!"):
                            base_prop_type = cleaned_type[:-1]
                        else:
                            base_prop_type = cleaned_type
                        
                        # Check if property type is valid
                        valid_prop_types = {"string", "number", "integer", "boolean", "object"}
                        if base_prop_type not in valid_prop_types:
                            return False
                    
                    return True
                else:
                    return False
                
            except (ValueError, SyntaxError, json.JSONDecodeError):
                return False
        
        return False

    # -----------------------------------------------------------------------------------------
    # LIST VALIDATION (delegates to CI single‑entry)
    # -----------------------------------------------------------------------------------------
    def _validate_agent_entries_list_logic(
        self,
        agent_cfg_list: Any,
        agent_name_ctx: str,
        proj_root: Optional[Path] = None,
    ) -> None:
        if not isinstance(agent_cfg_list, list):
            self.add_error(
                f"Agent configuration for '{agent_name_ctx}' must be a list, but found {type(agent_cfg_list).__name__}."
            )
            return
        if not agent_cfg_list:
            self.add_warning(f"Agent configuration list for '{agent_name_ctx}' is empty.")
            return
        for i, entry in enumerate(agent_cfg_list):
            self._validate_single_agent_entry_logic(entry, i, agent_name_ctx, proj_root)

    # -----------------------------------------------------------------------------------------
    # DEPENDENCY HELPERS (CI)
    # -----------------------------------------------------------------------------------------
    def _extract_dependencies_from_entry(self, entry: Dict[str, Any]) -> Set[str]:
        entry_ci = self._ci_dict(entry) if isinstance(entry, dict) else {}
        deps: Set[str] = set()
        if isinstance(entry_ci.get("dependencies"), list):
            deps.update(dep.lower() for dep in entry_ci["dependencies"] if isinstance(dep, str))
        return deps

    # -----------------------------------------------------------------------------------------
    # CONFIG‑WIDE VALIDATIONS (CI)
    # -----------------------------------------------------------------------------------------
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
        active_agents = {
            name.lower()
            for name, cfg in agent_cfgs_map.items()
            if isinstance(cfg, dict) and self._ci_dict(cfg).get("is_operational", True)
        }
        all_agents = {name.lower() for name in agent_cfgs_map}

        for agent_name, cfg in agent_cfgs_map.items():
            cfg_ci = self._ci_dict(cfg) if isinstance(cfg, dict) else {}
            if not cfg_ci.get("is_operational", True):
                continue
            deps = cfg_ci.get("dependencies", [])
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
                    if not dep_cfg_ci.get("is_operational", True):
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
                    cycle = " -> ".join(stack[cycle_idx:] + [neighbor])
                    self.add_error(f"Circular dependency detected: {cycle}.")
                    return True
            stack.pop()
            return False

        for n in list(graph):
            if n not in visited:
                dfs(n)

    # -----------------------------------------------------------------------------------------
    # PUBLIC ENTRY POINT
    # -----------------------------------------------------------------------------------------
    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """Run validation based on the *operation* key in ``data``."""
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
        cfg_path = data.get("config_path")
        agent_name = data.get("agent_name", Path(cfg_path).stem if isinstance(cfg_path, str) else None)
        if not (isinstance(cfg_path, str) and isinstance(agent_name, str) and project_root_path):
            self.add_error(
                "For 'validate_agent_config_file_meta', provide 'config_path' (str), 'agent_name' (str), and 'project_dir'."
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
            self._check_agent_name_unique_logic(agent_name, str(project_root_path), str(cfg_file.resolve()))

    def _validate_agent_entries_operation(
        self, data: Dict[str, Any], project_root_path: Optional[Path]
    ) -> None:
        cfg_list = data.get("agent_config_data")
        ctx_name = data.get("agent_name_context")
        if cfg_list is None or not isinstance(ctx_name, str):
            self.add_error("For 'validate_agent_entries', provide 'agent_config_data' and 'agent_name_context'.")
            return

        self._validate_agent_entries_list_logic(cfg_list, ctx_name, project_root_path)
