"""Backward-compatibility shim — ConfigManager moved to agent_actions.config.manager."""

from agent_actions.config.manager import ConfigManager

__all__ = ["ConfigManager"]
