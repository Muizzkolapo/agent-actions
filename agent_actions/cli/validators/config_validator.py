import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from agent_actions.handlers.file_handler import FileHandler
from .base_validator import BaseValidator

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
    _REQUIRED_AGENT_KEYS: Set[str] = {"agent_type", "model_name"}

    _OPTIONAL_AGENT_KEYS: Set[str] = {
        "description",
        "version",
        "author",
        "dependencies",
        "imports",
        "config",
        "parent",
        "granularity",
        "side_collection",
        "remove_collection",
        "model_vendor",
        "json_mode",
        "prompt_debug",
        "api_key",
        "prompt",
        "schema_name",
        "tools",
        "chunk_config",
        "use_few_shot_samples",
        "conditional_clause",
        "is_operational",
        "ephemeral",
    }

    _AGENT_TYPE_REQUIRED_KEYS: Dict[str, Set[str]] = {
        "llm": {"model_name"},
        "function": {"code_path"},
        "tool": {"model_name"},
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
        desc = f"agent entry {entry["agent_type"]} in '{cfg_ctx_name}'"
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
        model_vendor = str(entry_ci.get("model_vendor", "")).lower()
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
            if "side_collection" in entry_ci:
                self.add_error(
                    f"{desc} (model_vendor: 'tool', granularity: 'file') cannot have 'side_collection' defined. "
                    "This key should be removed for this agent configuration as file‑level tools process content wholesale, "
                    "and side_collection is for record‑level context enrichment."
                )
            if "remove_collection" in entry_ci:
                self.add_error(
                    f"{desc} (model_vendor: 'tool', granularity: 'file') cannot have 'remove_collection' defined. "
                    "This key should be removed for this agent configuration as file‑level tools process content wholesale, "
                    "and remove_collection is for modifying record‑level context."
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
        if "json_mode" in entry_ci and not isinstance(entry_ci["json_mode"], bool):
            self.add_error(f"{desc} 'json_mode' should be a boolean.")
        if "prompt_debug" in entry_ci and not isinstance(entry_ci["prompt_debug"], bool):
            self.add_error(f"{desc} 'prompt_debug' should be a boolean.")
        if "granularity" in entry_ci and granularity not in ["record", "file"]:
            self.add_error(f"{desc} 'granularity' must be 'record' or 'file'.")

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
    def _validate_config_dependencies_logic(self, full_config_data: Dict[str, List[Dict[str, Any]]]) -> None:
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

    def _check_circular_dependencies_logic(self, full_config_data: Dict[str, List[Dict[str, Any]]]) -> None:
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

        op_ok = True

        if operation == "validate_agent_config_file_meta":
            cfg_path = data.get("config_path")
            agent_name = data.get("agent_name", Path(cfg_path).stem if isinstance(cfg_path, str) else None)
            if not (isinstance(cfg_path, str) and isinstance(agent_name, str) and project_root_path):
                self.add_error(
                    "For 'validate_agent_config_file_meta', provide 'config_path' (str), 'agent_name' (str), and 'project_dir'."
                )
            else:
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

        elif operation == "validate_agent_entries":
            cfg_list = data.get("agent_config_data")
            ctx_name = data.get("agent_name_context")
            if cfg_list is None or not isinstance(ctx_name, str):
                self.add_error("For 'validate_agent_entries', provide 'agent_config_data' and 'agent_name_context'.")
            else:
                self._validate_agent_entries_list_logic(cfg_list, ctx_name, project_root_path)