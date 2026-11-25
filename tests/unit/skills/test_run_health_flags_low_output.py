"""The health check of the agac-operations skill flags an action that kept little output.

The script is copied into a user's skills directory and run with a plain ``python3``,
so it reads only public output: the ``agac dispositions --json`` report and the
action status file. It judges only finished actions: an action that ``--rerun``
reset can still show the counts of the old run until it runs again.
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "agent_actions"
    / "skills"
    / "agac-operations"
    / "scripts"
    / "run_health.py"
)


@pytest.fixture
def health():
    spec = importlib.util.spec_from_file_location("run_health_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(**counts_by_action):
    return {
        "workflow": "wf",
        "actions": [{"name": name, "counts": counts} for name, counts in counts_by_action.items()],
    }


def test_an_action_that_lost_most_records_is_above_the_limit(health):
    report = _report(write={"success": 74, "exhausted": 553}, review={"success": 600, "failed": 2})
    rows = health.check(report, {"write", "review"}, max_bad=0.2, min_records=20)
    by_name = {row["action"]: row for row in rows}
    assert by_name["write"]["above_limit"] and not by_name["review"]["above_limit"]


def test_an_action_that_is_not_finished_is_not_judged(health):
    report = _report(write={"success": 1, "exhausted": 900})
    assert health.check(report, {"other"}, max_bad=0.2, min_records=20) == []


def test_a_small_sample_is_not_judged(health):
    report = _report(write={"success": 1, "failed_checks": 4})
    assert not health.check(report, {"write"}, max_bad=0.2, min_records=20)[0]["above_limit"]


def test_exit_codes(health, tmp_path):
    status = tmp_path / ".agent_status.json"
    status.write_text(json.dumps({"write": {"status": "completed_with_failures"}}))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_report(write={"success": 10, "exhausted": 90})))
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_report(write={"success": 95, "failed": 5})))
    args = ["-w", "wf", "--status", str(status), "--counts"]
    assert health.main([*args, str(bad)]) == 1
    assert health.main([*args, str(good)]) == 0
    assert health.main([*args, str(tmp_path / "missing.json")]) == 2


def test_sandbox_reads_the_counts_and_status_of_sandbox_runs(health, tmp_path, monkeypatch):
    io_dir = tmp_path / "agent_workflow" / "wf" / "agent_io"
    (io_dir / "sandbox").mkdir(parents=True)
    (tmp_path / "agent_actions.yml").write_text("")
    (io_dir / ".agent_status.json").write_text(json.dumps({"write": {"status": "running"}}))
    (io_dir / "sandbox" / ".agent_status.json").write_text(
        json.dumps({"write": {"status": "completed"}})
    )
    commands = []

    def dispositions(command, **_):
        commands.append(command)
        report = json.dumps(_report(write={"success": 10, "exhausted": 90}))
        return subprocess.CompletedProcess(command, 0, stdout=report, stderr="")

    monkeypatch.setattr(health.subprocess, "run", dispositions)
    monkeypatch.chdir(tmp_path)
    assert health.main(["-w", "wf", "--sandbox"]) == 1
    assert commands[0][1:] == ["dispositions", "-w", "wf", "--json", "--sandbox"]
    assert health.main(["-w", "wf"]) == 0
    assert commands[1][1:] == ["dispositions", "-w", "wf", "--json"]
