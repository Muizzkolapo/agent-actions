"""Tests for the dispositions CLI command logic."""

from unittest.mock import MagicMock

from agent_actions.cli.dispositions import DispositionsCommand
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.unit.cli.conftest import make_mock_backend


class TestShowSummary:
    """DispositionsCommand._show_summary renders disposition table."""

    def test_summary_no_crash(self):
        backend = make_mock_backend(
            {
                "extract": [
                    {"record_id": "r1", "disposition": "success"},
                    {"record_id": "r2", "disposition": "success"},
                ],
                "classify": [
                    {"record_id": "r1", "disposition": "success"},
                    {"record_id": "r2", "disposition": "failed", "reason": "LLM error"},
                ],
            }
        )
        cmd = DispositionsCommand("test_workflow", action=None, quarantined=False)
        cmd.console = MagicMock()
        cmd._show_summary(backend, ["extract", "classify"])
        cmd.console.print.assert_called_once()

    def test_summary_excludes_node_level_records(self):
        backend = make_mock_backend(
            {
                "extract": [
                    {"record_id": NODE_LEVEL_RECORD_ID, "disposition": "success"},
                    {"record_id": "r1", "disposition": "success"},
                ],
            }
        )
        cmd = DispositionsCommand("test_workflow", action=None, quarantined=False)
        cmd.console = MagicMock()
        cmd._show_summary(backend, ["extract"])
        cmd.console.print.assert_called_once()

    def test_summary_skips_empty_actions(self):
        backend = make_mock_backend({})
        cmd = DispositionsCommand("test_workflow", action=None, quarantined=False)
        cmd.console = MagicMock()
        cmd._show_summary(backend, ["extract"])
        cmd.console.print.assert_called_once()


class TestShowQuarantined:
    """DispositionsCommand._show_quarantined shows failed/exhausted details."""

    def test_quarantined_shows_failed_records(self):
        backend = make_mock_backend(
            {
                "classify": [
                    {"record_id": "r2", "disposition": "failed", "reason": "LLM error"},
                    {"record_id": "r4", "disposition": "exhausted", "reason": "retry_exhausted"},
                ],
            }
        )
        cmd = DispositionsCommand("test_workflow", action=None, quarantined=True)
        cmd.console = MagicMock()
        cmd._show_quarantined(backend, ["extract", "classify"])
        call_args = cmd.console.print.call_args_list
        assert len(call_args) == 1

    def test_quarantined_empty(self):
        backend = make_mock_backend({})
        cmd = DispositionsCommand("test_workflow", action=None, quarantined=True)
        cmd.console = MagicMock()
        cmd._show_quarantined(backend, ["extract"])
        call_args = str(cmd.console.print.call_args_list[0])
        assert "No quarantined" in call_args
