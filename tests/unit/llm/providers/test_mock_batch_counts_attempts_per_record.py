"""The mock batch client counts the attempts of each record on its own.

A repair round submits a new, smaller batch that holds only the records that still
fail. Each record in it goes on from its own count, and a record left out keeps its
count, as the online mock counts per record.
"""

from __future__ import annotations

import pytest

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState

CONFIG = {
    "model_name": "agac-model",
    "json_mode": True,
    "compiled_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}


@pytest.fixture
def client(monkeypatch):
    seen: list[tuple[str, int]] = []
    original = AgacBatchClient._get_attempt_for_custom_id

    def spy(self, custom_id):
        attempt = original(self, custom_id)
        seen.append((custom_id, attempt))
        return attempt

    monkeypatch.setattr(AgacBatchClient, "_get_attempt_for_custom_id", spy)
    batch_client = AgacBatchClient()
    batch_client.seen = seen
    yield batch_client
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()


def _answer(client: AgacBatchClient, batch_id: str, record_ids: list[str]) -> list[tuple]:
    """Answer one batch of the records; returns each (custom_id, attempt) it used."""
    tasks = client.prepare_tasks(
        [
            {"target_id": rid, "content": {"source": {"text": rid}}, "prompt": "Summarise."}
            for rid in record_ids
        ],
        CONFIG,
    )
    AgacBatchClient._batches[batch_id] = MockBatchState(batch_id=batch_id, status="completed")
    AgacBatchClient._tasks_by_batch[batch_id] = tasks
    start = len(client.seen)
    client._fetch_raw_results(batch_id)
    return client.seen[start:]


def test_a_repair_batch_counts_on_from_each_record(client):
    assert _answer(client, "first", ["r1", "r2"]) == [("r1", 1), ("r2", 1)]

    assert _answer(client, "repair_1", ["r2"]) == [("r2", 2)]
    assert _answer(client, "repair_2", ["r1", "r2"]) == [("r1", 2), ("r2", 3)]
