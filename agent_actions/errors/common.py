"""Common errors used across multiple domains.

This module contains cross-cutting errors that don't belong to a specific domain.
"""
# pylint: disable=unnecessary-pass
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

from agent_actions.errors.base import AgentActionsError


class InvalidParameterError(AgentActionsError):
    """Raised when invalid or missing parameters are provided.

    This is a cross-cutting error used by multiple tool types.
    """

    pass
