"""Feature flag manager - simplified implementation."""

from typing import Any, Dict


class FeatureFlagContext:
    """Context for feature flags."""
    pass


def where_clause_enabled(agent_type: str) -> bool:
    """Check if WHERE clause is enabled."""
    return True


def where_clause_caching_enabled(agent_type: str) -> bool:
    """Check if WHERE clause caching is enabled."""
    return True


def where_clause_debug_enabled(agent_type: str) -> bool:
    """Check if WHERE clause debug is enabled."""
    return False


def where_clause_security_enabled(agent_type: str) -> bool:
    """Check if WHERE clause security is enabled."""
    return True