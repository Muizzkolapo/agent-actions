"""A submitted mock batch records the action's rules once, not once per task.

Every task of a batch carries the same rules, and the batch record is written again on
each poll. Collecting reads the rules back from the record, so the answers still meet
them; a record whose tasks carry no rules is answered by the plain generator.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState

SCHEMA = {
    "type": "object",
    "properties": {"invoice_id": {"type": "string"}, "summary": {"type": "string"}},
    "additionalProperties": False,
}
PATTERN = r"^INV-\d{4}$"
CONFIG = {
    "name": "extract",
    "model_name": "agac-model",
    "json_mode": True,
    "compiled_schema": SCHEMA,
    "expect": {
        "repair": "none",
        "expectations": [
            {"type": "matches_regex", "field": "invoice_id", "params": {"pattern": PATTERN}}
        ],
    },
}


@pytest.fixture
def project(tmp_path):
    from agent_actions.config.paths import PathManager
    from agent_actions.utils import path_utils

    root = tmp_path / "project"
    root.mkdir()
    (root / "agent_actions.yml").write_text("version: '1.0'\n")
    previous = path_utils._global_path_manager
    path_utils.set_path_manager(PathManager(project_root=root))
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()
    AgacBatchClient._contracts_by_batch.clear()
    yield root
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()
    AgacBatchClient._contracts_by_batch.clear()
    path_utils._global_path_manager = previous


def _collected(client: AgacBatchClient, batch_id: str) -> list[dict]:
    """The answers a later run collects, from the record alone."""
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()
    AgacBatchClient._contracts_by_batch.clear()
    lines = client._fetch_raw_results(batch_id).decode("utf-8").splitlines()
    return [
        json.loads(json.loads(line)["response"]["body"]["choices"][0]["message"]["content"])
        for line in lines
    ]


def test_the_rules_are_recorded_once_and_collected_answers_meet_them(project, tmp_path):
    client = AgacBatchClient(complete_after_seconds=0)
    rows = [
        {"target_id": f"r{i}", "content": {"source": {"n": i}}, "prompt": f"Extract {i}."}
        for i in range(50)
    ]
    tasks = client.prepare_tasks(rows, CONFIG)

    batch_id, _ = client.submit_batch(tasks, "extract", str(tmp_path / "out"))

    record = (project / ".agac" / "batch_state" / f"{batch_id}.json").read_text()
    assert record.count("INV-") == 1
    answers = _collected(client, batch_id)
    assert len(answers) == 50
    assert all(re.search(PATTERN, answer["invoice_id"]) for answer in answers), answers


def test_a_record_whose_tasks_carry_no_rules_is_answered_from_the_schema(project):
    task = {"custom_id": "r1", "prompt": "Extract.", "user_content": "{}", "schema": SCHEMA}
    AgacBatchClient._write_state(MockBatchState(batch_id="old", status="completed"), [task])

    [answer] = _collected(AgacBatchClient(), "old")

    assert set(answer) == set(SCHEMA["properties"])


def test_a_task_naming_rules_the_record_does_not_hold_is_logged(project, caplog):
    client = AgacBatchClient()
    client._tasks_by_batch["b1"] = [{"custom_id": "c1", "contract": "0123456789abcdef"}]
    client._contracts_by_batch["b1"] = {}
    client._batches["b1"] = {"status": "completed"}

    with caplog.at_level(logging.WARNING):
        client._fetch_raw_results("b1")

    assert "0123456789abcdef" in caplog.text
