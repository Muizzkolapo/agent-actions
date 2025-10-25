"""Artifact context for making artifact manager available to interceptors."""
import sys
from typing import Optional
from agent_actions.state_management.manager import ArtifactManager
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

# For backward compatibility, expose this module as 'context'
# This allows `from agent_actions.state_management.context import context`
context = sys.modules[__name__]