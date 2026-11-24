"""The mock batch client counts each submission of a record for its action, on disk.

A retry or repair batch is often submitted by a later run, a new process, so the count
lives in the project and a scenario's ``heal_on_attempt`` reads it there. Each record and
action counts on its own, and a scenario's faults go into the result lines at collect.
"""

from __future__ import annotations

import json

import pytest

from agent_actions.config import sandbox
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.utils.constants import RECORD_GUID_KEY

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def _config(action: str) -> dict:
    return {
        "name": action,
        "model_name": "agac-model",
        "json_mode": True,
        "compiled_schema": SCHEMA,
    }


@pytest.fixture
def project(tmp_path):
    from agent_actions.config.paths import PathManager
    from agent_actions.utils import path_utils

    previous = path_utils._global_path_manager
    path_utils.set_path_manager(PathManager(project_root=tmp_path))
    yield tmp_path
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()
    AgacBatchClient._contracts_by_batch.clear()
    path_utils._global_path_manager = previous


def _submit(project, action: str, record_ids: list[str]) -> str:
    client = AgacBatchClient()
    rows = [
        {
            "target_id": rid,
            "content": {"source": {"text": rid}},
            "prompt": "Sum up.",
            RECORD_GUID_KEY: f"g-{rid}",
        }
        for rid in record_ids
    ]
    tasks = client.prepare_tasks(rows, _config(action))
    path = project / "input.jsonl"
    path.write_text("\n".join(json.dumps(task) for task in tasks))
    batch_id, _ = client._submit_to_provider_api(path, "input")
    return batch_id


def _attempts(batch_id: str) -> dict[str, int]:
    return {t["custom_id"]: t["attempt"] for t in AgacBatchClient._tasks_by_batch[batch_id]}


def test_each_submission_of_a_record_is_its_next_attempt_in_any_process(project):
    first = _attempts(_submit(project, "extract", ["r1", "r2"]))
    # What a later run sees: nothing in memory.
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()

    again = _submit(project, "extract", ["r2"])
    other_action = _submit(project, "classify", ["r2"])

    assert first == {"r1": 1, "r2": 1}
    assert _attempts(again) == {"r2": 2}
    assert _attempts(other_action) == {"r2": 1}


def test_a_task_carries_its_record_and_the_request_does_not(project):
    batch_id = _submit(project, "extract", ["r1"])

    [task] = AgacBatchClient._tasks_by_batch[batch_id]
    assert task["record"] == "g-r1"
    assert RECORD_GUID_KEY not in json.dumps(task)


def _collected(project, scenario: str, record_ids: list[str]) -> list[dict]:
    (project / "sandbox.yml").write_text(scenario)
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(project, ["extract"])
        batch_id = _submit(project, "extract", record_ids)
        lines = AgacBatchClient()._fetch_raw_results(batch_id).decode().splitlines()
        summary = sandbox.scenario().summary()
    return [json.loads(line) for line in lines], summary


def test_a_scenario_error_is_the_record_s_failed_line_until_it_heals(project):
    scenario = "defaults:\n  errors: {rate: 1.0, kinds: [rate_limit], heal_on_attempt: 2}\n"

    first, summary = _collected(project, scenario, ["r1"])
    second, _ = _collected(project, scenario, ["r1"])

    assert first[0]["response"]["status_code"] == 429
    assert "1 errors" in summary
    assert second[0]["response"]["status_code"] == 200


def test_a_dropped_result_is_left_out_of_the_first_submission_only(project):
    first, summary = _collected(project, "batch: {drop_rate: 1.0}\n", ["r1", "r2"])
    second, _ = _collected(project, "batch: {drop_rate: 1.0}\n", ["r1", "r2"])

    assert first == []
    assert "2 batch results dropped" in summary
    assert [line["custom_id"] for line in second] == ["r1", "r2"]


def test_a_batch_of_an_action_the_scenario_fails_reports_failed(project):
    (project / "sandbox.yml").write_text("batch: {fail: [extract]}\n")
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(project, ["extract"])
        batch_id = _submit(project, "extract", ["r1"])

        assert AgacBatchClient()._fetch_status(batch_id) == "failed"
