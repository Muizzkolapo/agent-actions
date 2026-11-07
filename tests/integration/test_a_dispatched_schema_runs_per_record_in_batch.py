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
