"""`prompt_debug` prints each record's prompt when a batch is prepared, as an online call prints
it."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.realtime.builder import create_dynamic_agent
from tests.unit.llm.batch.recording_provider import RecordingProvider

PROMPT = "Summarise the document."
RECORDS = {"r1": {"doc": {"title": "Café", "n": [1, {"x": 2}]}}, "r2": {"doc": "second"}}
FEEDBACK = "Your previous output failed: the summary is empty."
INVOKE = "agent_actions.llm.realtime.builder.ClientInvocationService.invoke_client"


def _config(**extra: Any) -> dict[str, Any]:
    return {
        "agent_type": "summarize",
        "action_name": "summarize",
        "name": "summarize",
        "model_vendor": "openai",
        "model_name": "gpt-4o-mini",
        "json_mode": True,
        "granularity": "record",
        "prompt": PROMPT,
        "schema": {"summary": "string"},
        "context_scope": {"observe": ["source.doc"]},
        "prompt_debug": True,
        **extra,
    }


def _prepare(
    tmp_path: Any, config: dict[str, Any], feedback: dict[str, str] | None = None
) -> None:
    BatchTaskPreparator(storage_backend=MagicMock()).prepare_tasks(
        agent_config=config,
        data=[
            {"target_id": key, "source_guid": f"sg-{key}", "content": record}
            for key, record in RECORDS.items()
        ],
        provider=RecordingProvider(),
        output_directory=str(tmp_path),
        attempt=1 if feedback else 0,
        feedback_by_id=feedback,
    )


def _online_output(capsys: pytest.CaptureFixture[str], prompt: str = PROMPT) -> str:
    capsys.readouterr()
    with patch(INVOKE, return_value=[{"summary": "s"}]):
        for record in RECORDS.values():
            create_dynamic_agent(_config(), {"source": record}, prompt)
    return capsys.readouterr().out


def test_a_batch_prints_what_online_prints_for_the_same_records(tmp_path, capsys):
    online = _online_output(capsys)

    _prepare(tmp_path, _config())
    batch = capsys.readouterr().out

    assert batch == online
    assert batch.count("DEBUG MODE: Prompt being sent to the agent") == len(RECORDS)
    assert '{"source": {"doc": {"title": "Café", "n": [1, {"x": 2}]}}}' in batch
    assert '"summary"' in batch


def test_a_repair_round_prints_the_prompt_it_sends(tmp_path, capsys):
    online = _online_output(capsys, f"{PROMPT}\n\n{FEEDBACK}")

    _prepare(tmp_path, _config(), feedback={key: FEEDBACK for key in RECORDS})

    assert capsys.readouterr().out == online


def test_nothing_is_printed_without_prompt_debug(tmp_path, capsys):
    _prepare(tmp_path, _config(prompt_debug=False))

    assert capsys.readouterr().out == ""
