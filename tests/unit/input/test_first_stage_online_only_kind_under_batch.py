"""A first-stage tool or hitl action under run_mode: batch is staged for online."""

import json

import pytest

from agent_actions.config.types import RunMode
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    _check_and_prepare,
)

ROWS = [{"ticket_id": "T-1", "text": "Server is down"}]


def _stage(tmp_path, agent_config: dict):
    staging = tmp_path / "agent_io" / "staging"
    staging.mkdir(parents=True)
    target = tmp_path / "agent_io" / "target" / "first"
    target.mkdir(parents=True)
    doc = staging / "tickets.json"
    doc.write_text(json.dumps(ROWS))
    ctx = InitialStageContext(
        agent_config={
            "run_mode": RunMode.BATCH,
            "context_scope": {"observe": ["source.ticket_id"]},
            **agent_config,
        },
        agent_name="first",
        file_path=str(doc),
        base_directory=str(staging),
        output_directory=str(target),
        idx=0,
    )
    return _check_and_prepare(ctx, list(ROWS), ".json")


@pytest.mark.parametrize("kind", ["tool", "hitl"])
def test_an_online_only_kind_is_staged_online(tmp_path, kind):
    staged = _stage(tmp_path, {"kind": kind, "model_vendor": kind})

    assert staged.run_mode == RunMode.ONLINE
    assert all("batch_id" not in row for row in staged.data_chunk)


def test_an_llm_action_under_batch_is_still_staged_for_batch(tmp_path):
    staged = _stage(
        tmp_path,
        {"kind": "llm", "model_vendor": "openai", "prompt": "Label {{ source.ticket_id }}"},
    )

    assert staged.run_mode == RunMode.BATCH
    assert all("batch_id" in row for row in staged.data_chunk)
