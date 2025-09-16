import os
from contextlib import contextmanager
from typing import Dict, Optional


@contextmanager
def env_vars_context(env_vars: Dict[str, str]):
    """Temporarily set environment variables and restore them afterward."""
    # Store original env vars
    original_env = {}

    # Save original and set new values
    for key, value in env_vars.items():
        if key in os.environ:
            original_env[key] = os.environ[key]
        os.environ[key] = value

    try:
        yield
    finally:
        # Restore original values
        for key in env_vars:
            if key in original_env:
                os.environ[key] = original_env[key]
            else:
                del os.environ[key]


@contextmanager
def test_env_context(override_env_vars: Optional[Dict[str, str]] = None):
    """Set up test environment variables for agent-actions testing."""
    test_env = {
        "ENVIRONMENT": "testing",
        "OPENAI_API_KEY": "test-key-123",
        "ANTHROPIC_API_KEY": "test-key-456",
        "GOOGLE_API_KEY": "test-key-789",
        "AGENT_ACTIONS_LOG_LEVEL": "ERROR",
        "AGENT_ACTIONS_CACHE_ENABLED": "false",
        "AGENT_ACTIONS_PARALLEL_PROCESSING": "false",
        "PYTHONPATH": os.getcwd(),
    }

    if override_env_vars:
        test_env.update(override_env_vars)

    with env_vars_context(test_env):
        yield