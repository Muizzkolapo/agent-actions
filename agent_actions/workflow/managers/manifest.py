"""Manifest manager for workflow execution metadata."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from agent_actions.errors import ConfigurationError
from agent_actions.workflow.managers.state import COMPLETED_STATUSES, ActionStatus

logger = logging.getLogger(__name__)


class DuplicateActionError(ConfigurationError):
    """Raised when duplicate action names are detected in workflow configuration."""

    pass


MANIFEST_SCHEMA_VERSION = "1.0"
MANIFEST_FILENAME = ".manifest.json"


class ManifestManager:
    """Manages the workflow manifest file that tracks execution state and output directories."""

    def __init__(self, agent_io_path: Path):
        """Initialize manifest manager."""
        self.agent_io_path = Path(agent_io_path)
        self.target_dir = self.agent_io_path / "target"
        self.manifest_path = self.target_dir / MANIFEST_FILENAME
        self._manifest: dict[str, Any] | None = None
        self._lock = threading.RLock()

    @property
    def manifest(self) -> dict[str, Any]:
        """Return the current manifest, loading from disk if needed."""
        if self._manifest is None:
            with self._lock:
                if self._manifest is None:
                    self._manifest = self.load_manifest()
        return self._manifest

    def initialize_manifest(
        self,
        workflow_name: str,
        execution_order: list[str],
        levels: list[list[str]],
        action_configs: dict[str, dict[str, Any]],
        workflow_run_id: str | None = None,
    ) -> None:
        """Initialize a new manifest for a workflow run.

        Raises:
            DuplicateActionError: If duplicate action names are detected.
        """
        # Validate no duplicate action names
        seen = set()
        duplicates = []
        for action_name in execution_order:
            if action_name in seen:
                duplicates.append(action_name)
            seen.add(action_name)

        if duplicates:
            raise DuplicateActionError(
                f"Duplicate action names detected: {duplicates}. "
                "Each action must have a unique name."
            )

        if workflow_run_id is None:
            workflow_run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        with self._lock:
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
                action_config = action_configs.get(action_name, {})
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
                    "status": ActionStatus.PENDING,
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
            logger.debug("Initialized manifest for workflow %s", workflow_name)

    def load_manifest(self) -> dict[str, Any]:
        """Load manifest from disk, returning empty dict if not found."""
        if not self.manifest_path.exists():
            logger.debug("No manifest found at %s", self.manifest_path)
            return {}

        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

            # Validate schema version
            schema_version = manifest.get("schema_version")
            if schema_version != MANIFEST_SCHEMA_VERSION:
                logger.warning(
                    "Manifest schema version mismatch: expected %s, got %s",
                    MANIFEST_SCHEMA_VERSION,
                    schema_version,
                )

            return cast(dict[str, Any], manifest)
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
            except OSError as cleanup_err:
                logger.debug("Failed to clean up temp file %s: %s", tmp_path, cleanup_err)
            raise

    def get_output_directory(self, action_name: str) -> Path:
        """Return the output directory path for an action.

        Raises:
            KeyError: If action not found in manifest.
        """
        action = self.manifest.get("actions", {}).get(action_name)
        if not action:
            raise KeyError(f"Action '{action_name}' not found in manifest")
        return self.target_dir / cast(str, action["output_dir"])

    def get_dependency_directories(self, action_name: str) -> list[Path]:
        """Return output directories for all dependencies of an action."""
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

    def get_previous_action_directory(self, action_name: str) -> Path | None:
        """Return the output directory of the previous action, or None if first."""
        execution_order = self.manifest.get("execution_order", [])
        if action_name not in execution_order:
            return None

        idx = execution_order.index(action_name)
        if idx == 0:
            return None

        prev_action = execution_order[idx - 1]
        return self.get_output_directory(prev_action)

    def get_parallel_actions(self, level: int) -> list[str]:
        """Return all actions at a given execution level."""
        levels = self.manifest.get("levels", [])
        if level < 0 or level >= len(levels):
            return []
        return cast(list[str], levels[level])

    def get_action_index(self, action_name: str) -> int | None:
        """Return the execution index for an action, or None if not found."""
        action = self.manifest.get("actions", {}).get(action_name)
        if action:
            return cast(int | None, action.get("index"))
        return None

    def is_action_completed(self, action_name: str) -> bool:
        """Return True if action completed (including partial failures)."""
        action = self.manifest.get("actions", {}).get(action_name)
        return action is not None and action.get("status") in COMPLETED_STATUSES

    def is_action_skipped(self, action_name: str) -> bool:
        """Return True if action status is 'skipped'."""
        action = self.manifest.get("actions", {}).get(action_name)
        return action is not None and action.get("status") == ActionStatus.SKIPPED

    def mark_action_started(self, action_name: str) -> None:
        """Mark an action as started.

        Raises:
            KeyError: If action not found in manifest.
        """
        with self._lock:
            if action_name not in self.manifest.get("actions", {}):
                raise KeyError(f"Cannot mark unknown action '{action_name}' as started")

            if self._manifest is None:
                raise RuntimeError(
                    "ManifestManager._manifest is None; "
                    "initialize_manifest() or load_manifest() must be called first"
                )
            self._manifest["actions"][action_name]["status"] = ActionStatus.RUNNING
            self._manifest["actions"][action_name]["started_at"] = datetime.now().isoformat()
            self._save_manifest()

    def mark_action_completed(
        self,
        action_name: str,
        record_count: int | None = None,
        status: ActionStatus = ActionStatus.COMPLETED,
    ) -> None:
        """Mark an action as completed (or completed_with_failures).

        Raises:
            KeyError: If action not found in manifest.
        """
        with self._lock:
            if action_name not in self.manifest.get("actions", {}):
                raise KeyError(f"Cannot mark unknown action '{action_name}' as completed")

            if self._manifest is None:
                raise RuntimeError(
                    "ManifestManager._manifest is None; "
                    "initialize_manifest() or load_manifest() must be called first"
                )
            self._manifest["actions"][action_name]["status"] = status
            self._manifest["actions"][action_name]["completed_at"] = datetime.now().isoformat()
            if record_count is not None:
                self._manifest["actions"][action_name]["record_count"] = record_count
            self._save_manifest()

    def mark_action_skipped(self, action_name: str, reason: str | None = None) -> None:
        """Mark an action as skipped.

        Raises:
            KeyError: If action not found in manifest.
        """
        with self._lock:
            if action_name not in self.manifest.get("actions", {}):
                raise KeyError(f"Cannot mark unknown action '{action_name}' as skipped")

            if self._manifest is None:
                raise RuntimeError(
                    "ManifestManager._manifest is None; "
                    "initialize_manifest() or load_manifest() must be called first"
                )
            self._manifest["actions"][action_name]["status"] = ActionStatus.SKIPPED
            self._manifest["actions"][action_name]["completed_at"] = datetime.now().isoformat()
            if reason:
                self._manifest["actions"][action_name]["skip_reason"] = reason
            self._save_manifest()

    def mark_action_failed(self, action_name: str, error: str) -> None:
        """Mark an action as failed.

        Raises:
            KeyError: If action not found in manifest.
        """
        with self._lock:
            if action_name not in self.manifest.get("actions", {}):
                raise KeyError(f"Cannot mark unknown action '{action_name}' as failed")

            if self._manifest is None:
                raise RuntimeError(
                    "ManifestManager._manifest is None; "
                    "initialize_manifest() or load_manifest() must be called first"
                )
            self._manifest["actions"][action_name]["status"] = ActionStatus.FAILED
            self._manifest["actions"][action_name]["completed_at"] = datetime.now().isoformat()
            self._manifest["actions"][action_name]["error"] = error
            self._save_manifest()

    def mark_workflow_completed(self) -> None:
        """Mark the entire workflow as completed."""
        with self._lock:
            if self._manifest is None:
                raise RuntimeError(
                    "ManifestManager._manifest is None; "
                    "initialize_manifest() or load_manifest() must be called first"
                )
            self._manifest["status"] = "completed"
            self._manifest["completed_at"] = datetime.now().isoformat()
            self._save_manifest()

    def mark_workflow_failed(self, error: str) -> None:
        """Mark the entire workflow as failed."""
        with self._lock:
            if self._manifest is None:
                raise RuntimeError(
                    "ManifestManager._manifest is None; "
                    "initialize_manifest() or load_manifest() must be called first"
                )
            self._manifest["status"] = "failed"
            self._manifest["completed_at"] = datetime.now().isoformat()
            self._manifest["error"] = error
            self._save_manifest()

    def get_completed_actions(self) -> list[str]:
        """Return all completed action names (including partial failures)."""
        completed = []
        for action_name, action_data in self.manifest.get("actions", {}).items():
            if action_data.get("status") in COMPLETED_STATUSES:
                completed.append(action_name)
        return completed

    def get_upstream_actions(self, action_name: str) -> list[str]:
        """Return all actions upstream (lower index) of the given action."""
        current_idx = self.get_action_index(action_name)
        if current_idx is None:
            return []

        upstream = []
        for name, data in self.manifest.get("actions", {}).items():
            if data.get("index", 999) < current_idx:
                upstream.append(name)

        upstream.sort(key=lambda n: self.manifest["actions"][n]["index"])
        return upstream

    def has_manifest(self) -> bool:
        """Return True if a manifest file exists."""
        return self.manifest_path.exists()

    def clear_manifest(self) -> None:
        """Remove the manifest file."""
        with self._lock:
            if self.manifest_path.exists():
                self.manifest_path.unlink()
            self._manifest = None


__all__ = [
    "ManifestManager",
    "DuplicateActionError",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
]
