"""`artefact/runs.json` holds what each action's model calls used, and the run's total.

`actions[<name>].usage` is the five usage fields and, under `by_kind`, the sum per kind,
pricing and model. The run's `usage` and `total_tokens` are recomputed from its actions each
time, so setting one action's usage twice counts it once. The keys other tools read
(`actions[<name>].tokens`, `total_tokens`) keep their names and meaning.
"""

from __future__ import annotations

import json

from agent_actions.llm.providers.usage_tracker import prompt_and_completion, summarised
from agent_actions.tooling.docs.run_tracker import ActionCompleteConfig, RunTracker

FIELDS = [
    "calls",
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
]


def _row(kind: str, calls: int, *, batch: bool = False) -> dict:
    return {
        "kind": kind,
        "batch": batch,
        "model": "m",
        "calls": calls,
        "input_tokens": 10 * calls,
        "output_tokens": 2 * calls,
        "cache_read_input_tokens": 100 * calls,
        "cache_creation_input_tokens": 0,
    }


def _tracker(tmp_path, *actions: str) -> tuple[RunTracker, str]:
    tracker = RunTracker(artefact_dir=tmp_path)
    run_id = tracker.start_workflow_run(
        workflow_id="wf", workflow_name="wf", actions_total=len(actions)
    )
    for name in actions:
        tracker.record_action_start(
            run_id=run_id, action_name=name, action_type="llm", action_config={}
        )
    return tracker, run_id


def _record(tracker: RunTracker, run_id: str, action: str, rows: list[dict]) -> None:
    tracker.record_action_usage(
        run_id=run_id,
        action_name=action,
        usage=summarised(rows),
        tokens=prompt_and_completion(rows),
    )


def _run(tracker: RunTracker) -> dict:
    (run,) = json.loads(tracker.runs_file.read_text())["executions"]
    return run


def test_a_run_starts_with_a_total_of_nothing(tmp_path):
    tracker, _ = _tracker(tmp_path)

    run = _run(tracker)

    assert run["usage"] == dict.fromkeys(FIELDS, 0)
    assert run["total_tokens"] == 0


def test_an_action_s_usage_is_its_five_fields_broken_down_by_kind(tmp_path):
    tracker, run_id = _tracker(tmp_path, "write")
    rows = [_row("main", 2), _row("judge", 10, batch=True)]

    _record(tracker, run_id, "write", rows)

    assert _run(tracker)["actions"]["write"]["usage"] == {
        "calls": 12,
        "input_tokens": 120,
        "output_tokens": 24,
        "cache_read_input_tokens": 1200,
        "cache_creation_input_tokens": 0,
        "by_kind": rows,
    }


def test_the_keys_other_tools_read_keep_their_names_and_meaning(tmp_path):
    tracker, run_id = _tracker(tmp_path, "write")

    _record(tracker, run_id, "write", [_row("main", 2)])

    run = _run(tracker)
    assert run["actions"]["write"]["tokens"] == {
        "input_tokens": 220,
        "output_tokens": 4,
        "total_tokens": 224,
    }
    assert run["total_tokens"] == 224


def test_the_run_s_total_is_the_sum_over_its_actions(tmp_path):
    tracker, run_id = _tracker(tmp_path, "extract", "write")

    _record(tracker, run_id, "extract", [_row("main", 1)])
    _record(tracker, run_id, "write", [_row("main", 2), _row("repair", 1)])

    run = _run(tracker)
    assert run["usage"] == {
        "calls": 4,
        "input_tokens": 40,
        "output_tokens": 8,
        "cache_read_input_tokens": 400,
        "cache_creation_input_tokens": 0,
    }
    assert run["total_tokens"] == 448


def test_setting_an_action_s_usage_again_replaces_it_in_the_total(tmp_path):
    tracker, run_id = _tracker(tmp_path, "write")

    _record(tracker, run_id, "write", [_row("main", 1)])
    _record(tracker, run_id, "write", [_row("main", 3)])

    run = _run(tracker)
    assert run["usage"]["calls"] == 3
    assert run["total_tokens"] == 3 * 112


def test_completing_the_action_keeps_its_usage(tmp_path):
    tracker, run_id = _tracker(tmp_path, "write")
    _record(tracker, run_id, "write", [_row("main", 1)])

    tracker.record_action_complete(
        config=ActionCompleteConfig(
            run_id=run_id, action_name="write", status="success", duration_seconds=1.0
        )
    )

    entry = _run(tracker)["actions"]["write"]
    assert (entry["status"], entry["usage"]["calls"]) == ("success", 1)


def test_usage_for_an_action_the_run_never_started_writes_nothing(tmp_path):
    tracker, run_id = _tracker(tmp_path, "write")

    _record(tracker, run_id, "other", [_row("main", 1)])
    _record(tracker, "run_of_another_workflow", "write", [_row("main", 1)])

    run = _run(tracker)
    assert "other" not in run["actions"]
    assert "usage" not in run["actions"]["write"]
    assert run["total_tokens"] == 0


def test_calls_that_report_no_tokens_are_usage_without_a_tokens_entry(tmp_path):
    tracker, run_id = _tracker(tmp_path, "write")
    rows = [{**dict.fromkeys(FIELDS, 0), "kind": "main", "batch": False, "model": "m", "calls": 2}]

    _record(tracker, run_id, "write", rows)

    entry = _run(tracker)["actions"]["write"]
    assert entry["usage"]["calls"] == 2
    assert "tokens" not in entry
