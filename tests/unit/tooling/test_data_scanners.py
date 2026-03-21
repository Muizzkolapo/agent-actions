"""Regression tests for I-5: scan_logs() and extract_action_metrics() 100k-line cap."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.tooling.docs.scanner.data_scanners import extract_action_metrics, scan_logs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_events(path: Path, count: int, event_type: str = "CLIArgumentParsingEvent") -> None:
    """Write `count` minimal JSONL event lines to `path`."""
    with open(path, "w", encoding="utf-8") as f:
        for i in range(count):
            record = {
                "event_type": event_type,
                "meta": {"invocation_id": f"inv-{i}", "timestamp": "2024-01-01"},
                "data": {"command": "run"},
            }
            f.write(json.dumps(record) + "\n")


def _action_event(action_name: str) -> dict:
    return {
        "event_type": "ActionCompleteEvent",
        "meta": {"action_name": action_name},
        "data": {"action_name": action_name, "execution_time": 1.0, "record_count": 5},
    }


# ---------------------------------------------------------------------------
# scan_logs
# ---------------------------------------------------------------------------

class TestScanLogsLineCap:
    def test_scan_logs_returns_data_within_limit(self, tmp_path):
        """scan_logs returns correct data when under the line limit."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        _write_events(events_path, 50)
        result = scan_logs(tmp_path)
        assert isinstance(result["recent_invocations"], list)
        assert len(result["recent_invocations"]) <= 10  # capped at last 10

    def test_scan_logs_emits_warning_at_limit(self, tmp_path, capfd):
        """scan_logs emits a warning when the 100k-line cap is hit."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        # Write 100_001 lines so islice stops at 100_000 and the cap warning fires
        _write_events(events_path, 100_001)
        scan_logs(tmp_path)
        captured = capfd.readouterr()
        assert "line limit" in captured.err, (
            "Expected a 'line limit' warning on stderr when 100k-line cap is reached"
        )

    def test_scan_logs_no_warning_below_limit(self, tmp_path, capfd):
        """scan_logs does NOT emit a line-limit warning for small files."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        events_path = logs_dir / "events.json"
        _write_events(events_path, 10)
        scan_logs(tmp_path)
        captured = capfd.readouterr()
        assert "line limit" not in captured.err

    def test_scan_logs_missing_logs_dir(self, tmp_path):
        """scan_logs returns empty structure when logs/ does not exist."""
        result = scan_logs(tmp_path)
        assert result["events_path"] is None
        assert result["recent_invocations"] == []

    def test_scan_logs_missing_events_file(self, tmp_path):
        """scan_logs returns empty structure when events.json does not exist."""
        (tmp_path / "logs").mkdir()
        result = scan_logs(tmp_path)
        assert result["events_path"] is None


# ---------------------------------------------------------------------------
# extract_action_metrics
# ---------------------------------------------------------------------------

class TestExtractActionMetricsLineCap:
    def test_returns_metrics_for_known_events(self, tmp_path):
        """extract_action_metrics parses ActionCompleteEvent correctly."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_action_event("my_action")) + "\n")
        result = extract_action_metrics(events_path)
        assert "my_action" in result
        assert result["my_action"]["execution_time"] == 1.0

    def test_emits_warning_at_limit(self, tmp_path, capfd):
        """extract_action_metrics emits a warning when the 100k-line cap is hit."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            for i in range(100_001):
                f.write(json.dumps(_action_event(f"action_{i}")) + "\n")
        extract_action_metrics(events_path)
        captured = capfd.readouterr()
        assert "line limit" in captured.err

    def test_no_warning_below_limit(self, tmp_path, capfd):
        """extract_action_metrics does NOT warn for small files."""
        events_path = tmp_path / "events.json"
        with open(events_path, "w") as f:
            f.write(json.dumps(_action_event("act")) + "\n")
        extract_action_metrics(events_path)
        captured = capfd.readouterr()
        assert "line limit" not in captured.err
