"""Tests for _warn_orphaned_deferred false-positive elimination.

F3: The orphan DEFERRED warning must NOT fire when all records have terminal
dispositions (SUCCESS, FAILED, etc.) alongside their DEFERRED entries.
It MUST fire only for records that have DEFERRED and NO terminal sibling.
"""

import logging
from unittest.mock import MagicMock

import pytest

from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_SUCCESS,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager

LOGGER_NAME = "agent_actions.workflow.managers.batch"


def _make_disposition_lookup(
    rows: list[dict[str, str]],
):
    """Return a side_effect for get_disposition that filters by disposition kwarg."""

    def _lookup(action_name, disposition=None, **kwargs):
        if disposition is None:
            return rows
        return [r for r in rows if r.get("disposition") == disposition]

    return _lookup


@pytest.fixture
def mock_storage_backend():
    backend = MagicMock()
    backend.has_disposition.return_value = False
    return backend


@pytest.fixture
def manager(mock_storage_backend):
    return BatchLifecycleManager(
        job_manager=MagicMock(),
        processing_service=MagicMock(),
        storage_backend=mock_storage_backend,
    )


@pytest.fixture(autouse=True)
def _enable_log_propagation():
    """Ensure the agent_actions logger propagates so caplog can capture it."""
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = original


class TestOrphanDeferredWarning:
    """F3: orphan warning must distinguish genuine orphans from stale DEFERRED rows."""

    def test_no_warning_when_all_records_have_terminal_disposition(
        self, manager, mock_storage_backend, caplog
    ):
        """Records with DEFERRED + SUCCESS are NOT orphans — no warning."""
        rows = [
            {"record_id": "r1", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "r1", "disposition": DISPOSITION_SUCCESS},
            {"record_id": "r2", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "r2", "disposition": DISPOSITION_SUCCESS},
            {"record_id": "r3", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "r3", "disposition": DISPOSITION_FAILED},
        ]
        mock_storage_backend.get_disposition.side_effect = _make_disposition_lookup(rows)

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            manager._warn_orphaned_deferred("extract")

        assert "orphan" not in caplog.text.lower()

    def test_warning_fires_for_genuine_orphan(self, manager, mock_storage_backend, caplog):
        """Record with DEFERRED and no terminal sibling IS an orphan — warn."""
        rows = [
            {"record_id": "r1", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "r2", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "r2", "disposition": DISPOSITION_SUCCESS},
        ]
        mock_storage_backend.get_disposition.side_effect = _make_disposition_lookup(rows)

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            manager._warn_orphaned_deferred("extract")

        assert "1 record(s) still in DEFERRED state" in caplog.text
        assert "r1" in caplog.text
        assert "r2" not in caplog.text

    def test_no_warning_when_no_dispositions(self, manager, mock_storage_backend, caplog):
        """No dispositions at all — no warning."""
        mock_storage_backend.get_disposition.side_effect = _make_disposition_lookup([])

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            manager._warn_orphaned_deferred("extract")

        assert "orphan" not in caplog.text.lower()

    def test_warning_includes_only_orphan_ids(self, manager, mock_storage_backend, caplog):
        """Multiple orphans + multiple resolved — only orphan IDs appear."""
        rows = [
            {"record_id": "orphan1", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "orphan2", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "resolved1", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "resolved1", "disposition": DISPOSITION_SUCCESS},
            {"record_id": "resolved2", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "resolved2", "disposition": DISPOSITION_FILTERED},
        ]
        mock_storage_backend.get_disposition.side_effect = _make_disposition_lookup(rows)

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            manager._warn_orphaned_deferred("extract")

        assert "2 record(s) still in DEFERRED state" in caplog.text
        assert "orphan1" in caplog.text
        assert "orphan2" in caplog.text
        assert "resolved1" not in caplog.text
        assert "resolved2" not in caplog.text

    def test_exception_in_query_silently_handled(self, manager, mock_storage_backend, caplog):
        """Query failure does not raise — diagnostic only."""
        mock_storage_backend.get_disposition.side_effect = RuntimeError("db error")

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            manager._warn_orphaned_deferred("extract")

        assert "orphan" not in caplog.text.lower()

    def test_deferred_only_records_all_flagged(self, manager, mock_storage_backend, caplog):
        """All records DEFERRED with no terminal — all flagged as orphans."""
        rows = [
            {"record_id": "r1", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "r2", "disposition": DISPOSITION_DEFERRED},
            {"record_id": "r3", "disposition": DISPOSITION_DEFERRED},
        ]
        mock_storage_backend.get_disposition.side_effect = _make_disposition_lookup(rows)

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            manager._warn_orphaned_deferred("extract")

        assert "3 record(s) still in DEFERRED state" in caplog.text
