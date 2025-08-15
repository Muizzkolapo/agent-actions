"""Artifact context for making artifact manager available to interceptors."""

from typing import Optional
from .manager import ArtifactManager

# Global artifact manager context
_artifact_manager: Optional[ArtifactManager] = None


def set_artifact_manager(manager: ArtifactManager) -> None:
    """Set the global artifact manager for the current execution context."""
    global _artifact_manager
    _artifact_manager = manager


def get_artifact_manager() -> Optional[ArtifactManager]:
    """Get the current artifact manager if available."""
    return _artifact_manager


def clear_artifact_manager() -> None:
    """Clear the global artifact manager context."""
    global _artifact_manager
    _artifact_manager = None