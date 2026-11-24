"""A mock batch answers a record from what it is asked, not from the task's id.

The task id is a new one in each run. An answer seeded with it changes from run to
run, so a guard below the action lets other records through each time, and no two
batch runs of one workflow can be compared.
"""

import json

import pytest

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState

SCHEMA = {
    "name": "page_summary",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "score": {"type": "integer", "minimum": 0, "maximum": 1000000},
        },
        "required": ["summary", "score"],
        "additionalProperties": False,
    },
}


@pytest.fixture
def answers():
    """The parsed answers of one batch, by target id, through `prepare_tasks`."""

    def _answers(rows):
        client = AgacBatchClient()
        tasks = client.prepare_tasks(
            [
                {"target_id": target_id, "content": content, "prompt": "Summarise the page."}
                for target_id, content in rows
            ],
            {"model_name": "agac-model", "json_mode": True, "compiled_schema": SCHEMA},
        )
        AgacBatchClient._batches["b"] = MockBatchState(batch_id="b", status="completed")
        AgacBatchClient._tasks_by_batch["b"] = tasks
        lines = client._fetch_raw_results("b").decode("utf-8").strip().splitlines()
        return {
            (line := json.loads(raw))["custom_id"]: json.loads(
                line["response"]["body"]["choices"][0]["message"]["content"]
            )
            for raw in lines
        }

    yield _answers
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()


PAGE = {"source": {"page_content": "The tide turns twice a day."}}
OTHER_PAGE = {"source": {"page_content": "A neap tide has the smallest range."}}


def test_one_record_gets_one_answer_under_any_task_id(answers):
    first = answers([("run-1-id", PAGE)])["run-1-id"]
    second = answers([("run-2-id", PAGE)])["run-2-id"]

    assert first == second


def test_two_records_of_one_batch_get_their_own_answers(answers):
    got = answers([("a", PAGE), ("b", OTHER_PAGE)])

    assert got["a"] != got["b"]
