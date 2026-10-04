"""The collect step that finalize and a run with nothing to send share, against a real store."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.collect import collect_batch_rows
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "my_action"


@pytest.fixture
def backend(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    return backend


def _entry(guid: str, status: str, skip_reason: str | None = None) -> dict[str, Any]:
    entry = {
        "source_guid": guid,
        "target_id": f"t-{guid}",
        "content": {"source": {"item": guid}},
        "_batch_filter_status": status,
    }
    if skip_reason:
        entry["_batch_skip_reason"] = skip_reason
    return entry


def _failed_preparation(guid: str, context_map: dict[str, Any]) -> None:
    row = {"source_guid": guid, "target_id": f"t-{guid}", "content": {"source": {"item": guid}}}
    context_map[row["target_id"]] = {**row, "_state": "active"}
    BatchTaskPreparator._mark_prep_failed(
        row, context_map, ACTION, ValueError("references undefined variables: topic")
    )


def test_each_answer_is_recorded_on_the_prompt_that_asked_for_it(backend, tmp_path):
    """Finalize reaches its traces only through this step; a failed answer records none."""
    backend.write_prompt_trace(ACTION, "t-a1", "Ask about a1", source_guid="a1")
    backend.write_prompt_trace(ACTION, "t-a2", "Ask about a2", source_guid="a2")
    context_map = {
        "t-a1": _entry("a1", "included"),
        "t-a2": _entry("a2", "included"),
        "t-k1": _entry("k1", "skipped", "guard_skip"),
    }
    answered = [
        BatchResult(custom_id="t-a1", content={"answer": "ok"}, success=True),
        BatchResult(custom_id="t-a2", content=None, success=False, error="boom"),
    ]

    collect_batch_rows(
        backend,
        ACTION,
        {"action_name": ACTION},
        context_map,
        answered,
        output_directory=str(tmp_path),
    )

    traces = {
        trace["record_id"]: trace["response_text"] for trace in backend.get_prompt_traces(ACTION)
    }
    assert traces == {"t-a1": json.dumps({"answer": "ok"}), "t-a2": None}


@pytest.mark.parametrize(
    "agent_config",
    [{}, {"action_name": "other"}],
    ids=["config without a name", "config naming another action"],
)
def test_every_row_and_disposition_is_recorded_under_the_action_name_it_is_handed(
    backend, tmp_path, agent_config
):
    """Split between the config's name and the one passed, a record's row would sit
    under one action and its disposition under another, where neither reads it."""
    context_map = {
        "t-k1": _entry("k1", "skipped", "guard_skip"),
        "t-f1": _entry("f1", "filtered"),
    }
    _failed_preparation("p1", context_map)

    rows, _stats, _halt = collect_batch_rows(
        backend, ACTION, agent_config, context_map, [], output_directory=str(tmp_path)
    )

    assert {row["source_guid"]: row["content"][ACTION] for row in rows} == {"k1": None, "p1": None}
    assert [row for row in rows if "other" in row["content"]] == []
    assert sorted(
        (row["record_id"], row["disposition"]) for row in backend.get_disposition(ACTION)
    ) == [("f1", "filtered"), ("k1", "unprocessed"), ("p1", "failed")]
    assert backend.get_disposition("other") + backend.get_disposition("batch") == []
