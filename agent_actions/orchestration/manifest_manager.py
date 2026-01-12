"""
Manifest manager for workflow execution metadata.

Provides a single source of truth for action output directories and execution state,
replacing index-based directory naming with simple action names.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = "1.0"
MANIFEST_FILENAME = ".manifest.json"


class ManifestManager:
    """
    Manages the workflow manifest file that tracks execution state and output directories.

    The manifest is the single source of truth for:
    - Action output directory locations
    - Execution order and levels (for parallel execution)
    - Action status and metadata
    - Dependency relationships

    Manifest file location: {agent_io_path}/target/.manifest.json
    """

    def __init__(self, agent_io_path: Path):
        """
        Initialize manifest manager.

        Args:
            agent_io_path: Path to the agent_io directory (contains staging/, target/)
        """
        self.agent_io_path = Path(agent_io_path)
        self.target_dir = self.agent_io_path / "target"
        self.manifest_path = self.target_dir / MANIFEST_FILENAME
        self._manifest: Optional[Dict[str, Any]] = None

    @property
    def manifest(self) -> Dict[str, Any]:
        """Get the current manifest, loading from disk if needed."""
        if self._manifest is None:
            self._manifest = self.load_manifest()
        return self._manifest

    def initialize_manifest(
        self,
        workflow_name: str,
        execution_order: List[str],
        levels: List[List[str]],
        agent_configs: Dict[str, Dict[str, Any]],
        workflow_run_id: Optional[str] = None,
    ) -> None:
        """
        Initialize a new manifest for a workflow run.

        Args:
            workflow_name: Name of the workflow
            execution_order: List of action names in execution order
            levels: List of levels, each containing action names that run in parallel
            agent_configs: Dictionary of action configurations
            workflow_run_id: Optional run ID (generated if not provided)
        """
        if workflow_run_id is None:
            workflow_run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self._manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "workflow_name": workflow_name,
            "workflow_run_id": workflow_run_id,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "status": "running",
            "execution_order": execution_order,
            "levels": levels,
            "actions": {},
        }

        # Initialize action entries
        for idx, action_name in enumerate(execution_order):
            action_config = agent_configs.get(action_name, {})
            dependencies = action_config.get("dependencies", [])

            # Find which level this action belongs to
            action_level = 0
            for level_idx, level_actions in enumerate(levels):
                if action_name in level_actions:
                    action_level = level_idx
                    break

            self._manifest["actions"][action_name] = {
                "index": idx,
                "level": action_level,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "output_dir": action_name,  # Simple name, no index prefix
                "dependencies": dependencies,
                "record_count": None,
                "error": None,
            }

        # Ensure target directory exists and save
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self._save_manifest()
        logger.info("Initialized manifest for workflow %s", workflow_name)

    def load_manifest(self) -> Dict[str, Any]:
        """
        Load manifest from disk.

        Returns:
            Manifest dictionary, or empty dict if not found/invalid
        """
        if not self.manifest_path.exists():
            logger.debug("No manifest found at %s", self.manifest_path)
            return {}

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Validate schema version
            schema_version = manifest.get("schema_version")
            if schema_version != MANIFEST_SCHEMA_VERSION:
                logger.warning(
                    "Manifest schema version mismatch: expected %s, got %s",
                    MANIFEST_SCHEMA_VERSION,
                    schema_version,
                )

            return manifest
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load manifest from %s: %s", self.manifest_path, e)
            return {}

    def _save_manifest(self) -> None:
        """Save manifest to disk atomically."""
        if self._manifest is None:
            return

        self.target_dir.mkdir(parents=True, exist_ok=True)

        # Atomic write using temp file + rename
        fd, tmp_path = tempfile.mkstemp(dir=str(self.target_dir), prefix=".manifest_tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._manifest, f, indent=2)
            Path(tmp_path).replace(self.manifest_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_output_directory(self, action_name: str) -> Path:
        """
        Get the output directory path for an action.

        Args:
            action_name: Name of the action

        Returns:
            Path to the action's output directory

        Raises:
            KeyError: If action not found in manifest
        """
        action = self.manifest.get("actions", {}).get(action_name)
        if not action:
            raise KeyError(f"Action '{action_name}' not found in manifest")
        return self.target_dir / action["output_dir"]

    def get_dependency_directories(self, action_name: str) -> List[Path]:
        """
        Get output directories for all dependencies of an action.

        Args:
            action_name: Name of the action

        Returns:
            List of paths to dependency output directories
        """
        action = self.manifest.get("actions", {}).get(action_name)
        if not action:
            return []

        dep_dirs = []
        for dep_name in action.get("dependencies", []):
            try:
                dep_dirs.append(self.get_output_directory(dep_name))
            except KeyError:
                logger.warning(
                    "Dependency '%s' for action '%s' not found in manifest",
                    dep_name,
                    action_name,
                )
        return dep_dirs

    def get_previous_action_directory(self, action_name: str) -> Optional[Path]:
        """
        Get the output directory of the previous action in execution order.

        Args:
            action_name: Name of the current action

        Returns:
            Path to previous action's output directory, or None if first action
        """
        execution_order = self.manifest.get("execution_order", [])
        if action_name not in execution_order:
            return None

        idx = execution_order.index(action_name)
        if idx == 0:
            return None

        prev_action = execution_order[idx - 1]
        return self.get_output_directory(prev_action)

    def get_parallel_actions(self, level: int) -> List[str]:
        """
        Get all actions at a given execution level.

        Args:
            level: Execution level index

        Returns:
            List of action names at that level
        """
        levels = self.manifest.get("levels", [])
        if level < 0 or level >= len(levels):
            return []
        return levels[level]

    def get_action_index(self, action_name: str) -> Optional[int]:
        """
        Get the execution index for an action.

        Args:
            action_name: Name of the action

        Returns:
            Execution index, or None if not found
        """
        action = self.manifest.get("actions", {}).get(action_name)
        if action:
            return action.get("index")
        return None

    def is_action_completed(self, action_name: str) -> bool:
        """
        Check if an action has completed.

        Args:
            action_name: Name of the action

        Returns:
            True if action status is 'completed'
        """
        action = self.manifest.get("actions", {}).get(action_name)
        return action is not None and action.get("status") == "completed"

    def is_action_skipped(self, action_name: str) -> bool:
        """
        Check if an action was skipped.

        Args:
            action_name: Name of the action

        Returns:
            True if action status is 'skipped'
        """
        action = self.manifest.get("actions", {}).get(action_name)
        return action is not None and action.get("status") == "skipped"

    def mark_action_started(self, action_name: str) -> None:
        """
        Mark an action as started.

        Args:
            action_name: Name of the action
        """
        if action_name not in self.manifest.get("actions", {}):
            logger.warning("Cannot mark unknown action '%s' as started", action_name)
            return

        self._manifest["actions"][action_name]["status"] = "running"
        self._manifest["actions"][action_name]["started_at"] = datetime.now().isoformat()
        self._save_manifest()

    def mark_action_completed(
        self,
        action_name: str,
        record_count: Optional[int] = None,
    ) -> None:
        """
        Mark an action as completed.

        Args:
            action_name: Name of the action
            record_count: Optional count of records processed
        """
        if action_name not in self.manifest.get("actions", {}):
            logger.warning("Cannot mark unknown action '%s' as completed", action_name)
            return

        self._manifest["actions"][action_name]["status"] = "completed"
        self._manifest["actions"][action_name]["completed_at"] = datetime.now().isoformat()
        if record_count is not None:
            self._manifest["actions"][action_name]["record_count"] = record_count
        self._save_manifest()

    def mark_action_skipped(self, action_name: str, reason: Optional[str] = None) -> None:
        """
        Mark an action as skipped.

        Args:
            action_name: Name of the action
            reason: Optional reason for skipping
        """
        if action_name not in self.manifest.get("actions", {}):
            logger.warning("Cannot mark unknown action '%s' as skipped", action_name)
            return

        self._manifest["actions"][action_name]["status"] = "skipped"
        self._manifest["actions"][action_name]["completed_at"] = datetime.now().isoformat()
        if reason:
            self._manifest["actions"][action_name]["skip_reason"] = reason
        self._save_manifest()

    def mark_action_failed(self, action_name: str, error: str) -> None:
        """
        Mark an action as failed.

        Args:
            action_name: Name of the action
            error: Error message
        """
        if action_name not in self.manifest.get("actions", {}):
            logger.warning("Cannot mark unknown action '%s' as failed", action_name)
            return

        self._manifest["actions"][action_name]["status"] = "failed"
        self._manifest["actions"][action_name]["completed_at"] = datetime.now().isoformat()
        self._manifest["actions"][action_name]["error"] = error
        self._save_manifest()

    def mark_workflow_completed(self) -> None:
        """Mark the entire workflow as completed."""
        self._manifest["status"] = "completed"
        self._manifest["completed_at"] = datetime.now().isoformat()
        self._save_manifest()

    def mark_workflow_failed(self, error: str) -> None:
        """Mark the entire workflow as failed."""
        self._manifest["status"] = "failed"
        self._manifest["completed_at"] = datetime.now().isoformat()
        self._manifest["error"] = error
        self._save_manifest()

    def get_completed_actions(self) -> List[str]:
        """
        Get list of all completed action names.

        Returns:
            List of action names with 'completed' status
        """
        completed = []
        for action_name, action_data in self.manifest.get("actions", {}).items():
            if action_data.get("status") == "completed":
                completed.append(action_name)
        return completed

    def get_upstream_actions(self, action_name: str) -> List[str]:
        """
        Get all actions that are upstream (have lower index) of the given action.

        Args:
            action_name: Name of the action

        Returns:
            List of upstream action names
        """
        current_idx = self.get_action_index(action_name)
        if current_idx is None:
            return []

        upstream = []
        for name, data in self.manifest.get("actions", {}).items():
            if data.get("index", 999) < current_idx:
                upstream.append(name)

        # Sort by index
        upstream.sort(key=lambda n: self.manifest["actions"][n]["index"])
        return upstream

    def has_manifest(self) -> bool:
        """Check if a manifest file exists."""
        return self.manifest_path.exists()

    def clear_manifest(self) -> None:
        """Remove the manifest file."""
        if self.manifest_path.exists():
            self.manifest_path.unlink()
        self._manifest = None


__all__ = ["ManifestManager", "MANIFEST_FILENAME", "MANIFEST_SCHEMA_VERSION"]
