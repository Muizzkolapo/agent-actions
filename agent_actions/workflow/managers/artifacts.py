"""Artifact linking for workflow input/output management."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


class ArtifactLinker:
    """Manages artifact linking between workflows via manifest files."""

    MANIFEST_FILENAME = ".upstream_manifest.json"

    def __init__(self, workflows_root: Path):
        """Initialize artifact linker."""
        self.workflows_root = workflows_root

    def link_workflow_artifacts(
        self,
        source_workflow: str,
        target_workflow: str,
        source_action: str | None = None,
    ) -> None:
        """Link source workflow's output to target workflow via manifest.

        Args:
            source_workflow: Name of the upstream workflow.
            target_workflow: Name of the downstream workflow.
            source_action: Specific action in the source workflow to link.
                When provided, links that action's output directory directly
                instead of guessing via mtime.  This is critical for
                cross-workflow deps where the downstream declares exactly
                which upstream action it consumes.
        """
        source_target = self.workflows_root / source_workflow / "agent_io" / "target"
        target_io = self.workflows_root / target_workflow / "agent_io"

        if not source_target.exists():
            logger.warning("Source target directory does not exist: %s", source_target)
            return

        if source_action:
            # Link to the specific action's output directory.
            action_dir = source_target / source_action
            if action_dir.is_dir():
                latest_node = action_dir
            else:
                # Action output is in SQLite (no filesystem directory).
                # Create a virtual directory so the manifest path encodes
                # the action name — the runner uses path.name to look up
                # data in the storage backend.
                action_dir.mkdir(parents=True, exist_ok=True)
                logger.debug(
                    "Created virtual directory for SQLite-backed action: %s",
                    action_dir,
                )
                latest_node = action_dir
        else:
            latest_node = self.find_latest_node_dir(source_target)

        if not latest_node:
            logger.warning("No output nodes found in %s", source_target)
            return

        if not self.validate_safe_path(latest_node, self.workflows_root):
            logger.warning("Rejecting link: source %s outside workspace", latest_node)
            return
        if not self.validate_safe_path(target_io, self.workflows_root):
            logger.warning("Rejecting link: target %s outside workspace", target_io)
            return

        self._write_upstream_manifest(target_io, source_workflow, latest_node)
        logger.info("Wrote manifest linking %s -> %s", source_workflow, target_workflow)

    def link_upstream_artifacts(
        self,
        upstream_name: str,
        current_workflow: str,
        source_action: str | None = None,
    ) -> None:
        """Link upstream workflow's output to current workflow via manifest."""
        self.link_workflow_artifacts(upstream_name, current_workflow, source_action=source_action)

    def link_downstream_artifacts(
        self,
        current_workflow: str,
        downstream_name: str,
        source_action: str | None = None,
    ) -> None:
        """Link current workflow's output to downstream workflow via manifest."""
        self.link_workflow_artifacts(current_workflow, downstream_name, source_action=source_action)

    def _write_upstream_manifest(
        self, target_io: Path, source_workflow: str, source_node: Path
    ) -> None:
        """Write manifest file pointing to upstream workflow's output (atomic write)."""
        manifest_file = target_io / self.MANIFEST_FILENAME
        target_io.mkdir(parents=True, exist_ok=True)

        files = []
        for item in source_node.iterdir():
            if item.is_file() and not item.name.startswith("."):
                files.append(item.name)

        manifest: dict[str, Any] = {
            "upstream_workflow": source_workflow,
            "upstream_path": str(source_node),
            "files": sorted(files),
        }

        fd, tmp_path = tempfile.mkstemp(dir=str(target_io), prefix=".manifest_tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            Path(tmp_path).replace(manifest_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError as cleanup_err:
                logger.debug("Failed to clean up temp file %s: %s", tmp_path, cleanup_err)
            raise

    def find_latest_node_dir(self, target_dir: Path) -> Path | None:
        """Return the most recently modified action directory in target, or None."""
        action_dirs = [p for p in target_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if not action_dirs:
            return None
        return max(action_dirs, key=lambda p: p.stat().st_mtime)

    def validate_safe_path(self, path: Path, base_dir: Path) -> bool:
        """Return True if path is safely within base_dir (path traversal protection)."""
        try:
            resolved = path.resolve()
            base_resolved = base_dir.resolve()
            resolved.relative_to(base_resolved)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def read_manifest(agent_io_dir: Path) -> dict[str, Any] | None:
        """Read upstream manifest from agent_io directory, or None if absent/invalid."""
        manifest_file = agent_io_dir / ArtifactLinker.MANIFEST_FILENAME
        if not manifest_file.exists():
            return None

        try:
            with open(manifest_file, encoding="utf-8") as f:
                manifest = json.load(f)

            if not all(k in manifest for k in ("upstream_workflow", "upstream_path")):
                logger.warning("Manifest missing required fields: %s", manifest_file)
                return None

            return cast(dict[str, Any], manifest)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read manifest %s: %s", manifest_file, e)
            return None


__all__ = ["ArtifactLinker"]
