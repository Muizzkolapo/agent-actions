"""Shared test fixtures for CLI command tests."""

import sys
from unittest.mock import MagicMock

import pytest


def make_mock_backend(dispositions: dict[str, list[dict]] | None = None):
    """Create a mock storage backend with disposition data.

    Args:
        dispositions: Mapping of action_name → list of disposition dicts.
            Each dict should have at minimum ``record_id`` and ``disposition``.
    """
    dispositions = dispositions or {}
    backend = MagicMock()
    # A real backend answers `str | None`; left as a bare MagicMock it answers a
    # MagicMock, and any caller that parses the metadata — the batch registry
    # does — fails on the mock rather than on what the test is about.
    backend.load_metadata.return_value = None

    def get_disposition(action_name, record_id=None, disposition=None, *, snapshots=True):
        rows = dispositions.get(action_name, [])
        if disposition:
            rows = [r for r in rows if r.get("disposition") == disposition]
        if record_id:
            rows = [r for r in rows if r.get("record_id") == record_id]
        return rows

    backend.get_disposition = MagicMock(side_effect=get_disposition)
    backend.clear_disposition = MagicMock(return_value=1)
    return backend


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
