"""Shared test fixtures for CLI command tests."""

from unittest.mock import MagicMock


def make_mock_backend(dispositions: dict[str, list[dict]] | None = None):
    """Create a mock storage backend with disposition data.

    Args:
        dispositions: Mapping of action_name → list of disposition dicts.
            Each dict should have at minimum ``record_id`` and ``disposition``.
    """
    dispositions = dispositions or {}
    backend = MagicMock()

    def get_disposition(action_name, record_id=None, disposition=None):
        rows = dispositions.get(action_name, [])
        if disposition:
            rows = [r for r in rows if r.get("disposition") == disposition]
        if record_id:
            rows = [r for r in rows if r.get("record_id") == record_id]
        return rows

    backend.get_disposition = MagicMock(side_effect=get_disposition)
    backend.clear_disposition = MagicMock(return_value=1)
    return backend
