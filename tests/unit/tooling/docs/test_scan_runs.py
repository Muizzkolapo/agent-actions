"""Tests for scan_runs event-log reads."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

from agent_actions.tooling.docs.scanner.data_scanners import scan_runs


def _action_event(action_name: str) -> dict:
    return {
        "event_type": "ActionCompleteEvent",
        "meta": {"action_name": action_name},
        "data": {"action_name": action_name, "execution_time": 1.0, "record_count": 5},
    }


def _warn_event(action_name: str, message: str, level: str = "warn") -> dict:
    return {
        "event_type": "LogEvent",
        "code": "X000",
        "level": level,
        "message": message,
        "meta": {"timestamp": "2026-04-03T09:44:13Z", "action_name": action_name},
        "data": {},
    }


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "agent_config").mkdir()
    (tmp_path / "agent_config" / "wf.yml").write_text("name: wf\n")
    logs_dir = tmp_path / "agent_io" / "logs"
    logs_dir.mkdir(parents=True)
    events_path = logs_dir / "events.json"
    with open(events_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(_action_event("my_action")) + "\n")
        f.write(json.dumps(_warn_event("my_action", "records filtered")) + "\n")
    return events_path


class TestScanRunsReadsEventLogOnce:
    def test_event_log_is_read_once(self, tmp_path, monkeypatch):
        """Metrics and runtime warnings come from a single pass over events.json."""
        events_path = _make_project(tmp_path)

        opened: list[str] = []
        real_open = builtins.open

        def counting_open(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", counting_open)
        result = scan_runs(tmp_path)
        monkeypatch.undo()

        run = result["wf"]
        assert run["action_metrics"]["my_action"]["execution_time"] == 1.0
        assert [w["message"] for w in run["runtime_warnings"]] == ["records filtered"]
        assert opened.count(str(events_path)) == 1


class TestScanRunsSurfacesTheEventTail:
    """The one seam that carries a workflow's tail to the catalog generator."""

    def test_the_tail_reaches_runs_data(self, tmp_path):
        (tmp_path / "agent_config").mkdir()
        (tmp_path / "agent_config" / "wf.yml").write_text("name: wf\n")
        logs_dir = tmp_path / "agent_io" / "logs"
        logs_dir.mkdir(parents=True)
        with open(logs_dir / "events.json", "w", encoding="utf-8") as f:
            for i in range(3):
                f.write(
                    json.dumps(
                        {
                            "event_type": "ActionCompleteEvent",
                            "diagnostic": i == 1,
                            "meta": {"timestamp": f"2026-09-22T10:00:0{i}Z"},
                            "data": {"action_name": f"step_{i}"},
                        }
                    )
                    + "\n"
                )

        rows = scan_runs(tmp_path)["wf"]["events"]

        assert [r["seq"] for r in rows] == [0, 1, 2]
        assert [r["data"]["action_name"] for r in rows] == ["step_0", "step_1", "step_2"]
        assert [r["diagnostic"] for r in rows] == [False, True, False]
