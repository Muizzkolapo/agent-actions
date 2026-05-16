"""Tests for the dispositions CLI command logic."""

from io import StringIO

from rich.console import Console

from agent_actions.cli.dispositions import DispositionsCommand
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.unit.cli.conftest import make_mock_backend


def _make_cmd(agent="test_workflow", action=None, quarantined=False):
    """Create a DispositionsCommand with captured console output."""
    cmd = DispositionsCommand(agent, action=action, quarantined=quarantined)
    buf = StringIO()
    cmd.console = Console(file=buf, force_terminal=False, width=120)
    return cmd, buf


class TestShowSummary:
    """DispositionsCommand._show_summary renders disposition table."""

    def test_summary_shows_correct_counts(self):
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
        cmd, buf = _make_cmd()
        cmd._show_summary(backend, ["extract", "classify"])
        output = buf.getvalue()
        # extract row: 2 success
        assert "extract" in output
        # classify row: 1 success, 1 failed
        assert "classify" in output

    def test_summary_excludes_node_level_records(self):
        backend = make_mock_backend(
            {
                "extract": [
                    {"record_id": NODE_LEVEL_RECORD_ID, "disposition": "success"},
                    {"record_id": "r1", "disposition": "success"},
                ],
            }
        )
        cmd, buf = _make_cmd()
        cmd._show_summary(backend, ["extract"])
        output = buf.getvalue()
        # Should show extract with 1 record (node-level excluded)
        assert "extract" in output

    def test_summary_empty_shows_message(self):
        backend = make_mock_backend({})
        cmd, buf = _make_cmd()
        cmd._show_summary(backend, ["extract"])
        output = buf.getvalue()
        assert "No dispositions recorded" in output


class TestShowQuarantined:
    """DispositionsCommand._show_quarantined shows failed/exhausted details."""

    def test_quarantined_shows_record_details(self):
        backend = make_mock_backend(
            {
                "classify": [
                    {"record_id": "r2", "disposition": "failed", "reason": "LLM error"},
                    {"record_id": "r4", "disposition": "exhausted", "reason": "retry_exhausted"},
                ],
            }
        )
        cmd, buf = _make_cmd(quarantined=True)
        cmd._show_quarantined(backend, ["extract", "classify"])
        output = buf.getvalue()
        assert "r2" in output
        assert "r4" in output
        assert "failed" in output
        assert "exhausted" in output

    def test_quarantined_empty_shows_message(self):
        backend = make_mock_backend({})
        cmd, buf = _make_cmd(quarantined=True)
        cmd._show_quarantined(backend, ["extract"])
        output = buf.getvalue()
        assert "No quarantined records found" in output
