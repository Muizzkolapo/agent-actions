"""`schema: dispatch_task('fn')` gives each batch row the schema its function picks.

Batch compiled one schema for the whole action, with no record to hand the function, so a
schema chosen per record could not reach the rows at all.
"""

from __future__ import annotations

import json

from tests._support.agac_cli import run_agac
from tests.integration.test_a_dispatched_schema_runs_per_record import (
    keys_by_page,
    project,
    schemas_by_page,
)

_BATCH_NOW = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}


def test_each_batch_task_carries_the_schema_its_record_was_given(tmp_path):
    root = project(tmp_path, run_mode="batch")

    submitted = run_agac(root, "run", "-a", "w", "--fresh", env=_BATCH_NOW)

    assert submitted.returncode == 0, submitted.stdout + submitted.stderr
    (batch,) = (root / ".agac" / "batch_state").glob("*.json")
    tasks = json.loads(batch.read_text())["tasks"]
    assert len(tasks) == 2
    schemas = [json.dumps(task) for task in tasks]
    assert sum('"topic"' in s and '"verdict"' not in s for s in schemas) == 1
    assert sum('"verdict"' in s and '"topic"' not in s for s in schemas) == 1


def test_each_batch_row_answers_in_the_schema_its_function_picked(tmp_path):
    root = project(tmp_path, run_mode="batch")

    output = ""
    for args in (("--fresh",), (), (), ()):
        result = run_agac(root, "run", "-a", "w", *args, env=_BATCH_NOW)
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        if "run again" not in output:
            break
    assert "run again" not in output, output

    keys = keys_by_page(root)
    assert "topic" in keys["p1"] and "verdict" not in keys["p1"]
    assert "verdict" in keys["p2"] and "topic" not in keys["p2"]
    assert schemas_by_page(root) == {"p1": "topic_answer", "p2": "verdict_answer"}


_RAISES = """\
def dsp_pick_schema(context_json):
    raise AssertionError("a retry round must not call the dispatch function again")
"""


def test_a_retry_round_in_a_new_process_uses_the_recorded_choice(tmp_path):
    """A record the provider lost is sent again by a later run, a new process: the stored
    context map gives it the schema its first round chose, and the function is not called."""
    root = project(tmp_path, run_mode="batch")
    config = root / "agent_workflow" / "w" / "agent_config" / "w.yml"
    config.write_text(
        config.read_text().replace(
            "    prompt: $w.Label\n",
            "    prompt: $w.Label\n    retry: { enabled: true, max_attempts: 3 }\n",
        )
    )
    submitted = run_agac(root, "run", "-a", "w", "--fresh", env=_BATCH_NOW)
    assert submitted.returncode == 0, submitted.stdout + submitted.stderr
    (batch,) = (root / ".agac" / "batch_state").glob("*.json")
    held = json.loads(batch.read_text())
    held["tasks"] = held["tasks"][1:]
    batch.write_text(json.dumps(held))
    (root / "tools" / "w" / "dsp_pick_schema.py").write_text(_RAISES)

    output = ""
    for _ in range(4):
        result = run_agac(root, "run", "-a", "w", env=_BATCH_NOW)
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        if "run again" not in output:
            break

    assert "AssertionError" not in output, output
    keys = keys_by_page(root)
    assert keys == {"p1": {"topic"}, "p2": {"verdict"}}, output
    assert schemas_by_page(root) == {"p1": "topic_answer", "p2": "verdict_answer"}
