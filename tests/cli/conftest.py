"""Shared fixtures for the CLI tests."""

import sys

import pytest


@pytest.fixture
def isolated_user_tools():
    """Undo what running a project's tools registers, so the next project discovers afresh.

    Discovery skips a tools file whose synthetic module is already in ``sys.modules``,
    and ``@expectation_check`` refuses a second file claiming a registered name. A test
    that runs a workflow from a tmp copy of a fixture project must leave neither behind,
    or a later test running another copy of the same project fails on the collision.
    """
    from agent_actions.expectations import registry as expectation_registry
    from agent_actions.utils.udf_management.registry import clear_registry

    saved_registry = dict(expectation_registry._REGISTRY)
    saved_sources = dict(expectation_registry._USER_CHECK_SOURCES)
    _forget_user_tools(clear_registry)
    yield
    _forget_user_tools(clear_registry)
    expectation_registry._REGISTRY.clear()
    expectation_registry._REGISTRY.update(saved_registry)
    expectation_registry._USER_CHECK_SOURCES.clear()
    expectation_registry._USER_CHECK_SOURCES.update(saved_sources)


def _forget_user_tools(clear_registry) -> None:
    clear_registry()
    for name in [k for k in sys.modules if k.startswith("agent_actions._udfs.")]:
        sys.modules.pop(name, None)
