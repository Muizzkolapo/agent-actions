"""Shared fixtures for the CLI tests."""

import sys

import pytest


@pytest.fixture
def isolated_user_tools():
    """Undo what running a project's tools registers, so the next project discovers afresh.

    Discovery skips a tools file whose synthetic module is already in ``sys.modules``,
    so a test that runs a workflow from a tmp copy of a fixture project must not leave
    its modules behind. The root conftest restores the expectation checks it registers.
    """
    from agent_actions.utils.udf_management.registry import clear_registry

    _forget_user_tools(clear_registry)
    yield
    _forget_user_tools(clear_registry)


def _forget_user_tools(clear_registry) -> None:
    clear_registry()
    for name in [k for k in sys.modules if k.startswith("agent_actions._udfs.")]:
        sys.modules.pop(name, None)
