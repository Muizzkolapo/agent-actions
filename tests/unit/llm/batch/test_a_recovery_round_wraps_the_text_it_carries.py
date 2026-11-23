"""A recovery round puts a carried text-mode answer under its output field, as retrieval does."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_models import BatchJobEntry, RecoveryType
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.batch_base import BatchResult

PLAIN_TEXT = "Q1: PASS | difficulty 3"

VALIDATOR = {
    "name": "validate",
    "action_name": "validate",
    "agent_type": "validate",
    "json_mode": False,
    "output_field": "verdicts",
    "model_name": "test-model",
    "prompt": "Check the question.",
    "run_mode": "batch",
    "schema": {"verdicts": "string"},
    "expect": {"repair": "auto", "structural": "auto"},
}


def _anthropic_line(text: str) -> dict[str, Any]:
    return {
        "custom_id": "r1",
        "result": {
            "type": "succeeded",
            "message": {
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        },
    }


class _Provider:
    def __init__(self, *texts: str) -> None:
        client = AnthropicBatchClient(api_key="sk-ant-test")
        self._results = [client.parse_provider_response(_anthropic_line(t)) for t in texts]

    def retrieve_results(self, batch_id: str, output_directory: str | None) -> list[BatchResult]:
        return self._results


def _run(accumulated_rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    service = MagicMock()
    service._resolve_action_name.side_effect = lambda name: name or "validate"
    service._apply_workflow_session_id.side_effect = lambda config, entry: config
    service._client_resolver.get_for_batch_id.return_value = _Provider(PLAIN_TEXT)
    service._context_manager.load_batch_context_map.return_value = {}
    entry = BatchJobEntry(
        batch_id="b2",
        status="completed",
        timestamp="t",
        provider="anthropic",
        file_name="f.json_repair_1",
        parent_file_name="f.json",
        recovery_type=RecoveryType.REPAIR,
        recovery_attempt=1,
    )
    seen: dict[str, Any] = {}

    def handler(context, identity, *, state, recovery_results, accumulated, context_map):
        seen["recovery"], seen["accumulated"] = recovery_results, accumulated
        return "done"

    state = SimpleNamespace(accumulated_results=accumulated_rows)
    with (
        patch.object(pr.RecoveryStateManager, "load", return_value=state),
        patch.object(pr, "handle_repair_recovery", handler),
    ):
        pr.process_recovery_batch(
            service, "b2", "f.json_repair_1", entry, "/tmp/out", dict(config), MagicMock()
        )
    return seen


def test_the_retrieved_round_is_under_the_output_field():
    seen = _run([], VALIDATOR)

    assert [r.content for r in seen["recovery"]] == [{"verdicts": PLAIN_TEXT}]


def test_a_text_answer_carried_from_a_state_an_earlier_version_wrote_is_wrapped():
    seen = _run(
        [{"custom_id": "r0", "success": True, "content": "Q1: FAIL | difficulty 2"}], VALIDATOR
    )

    assert [r.content for r in seen["accumulated"]] == [{"verdicts": "Q1: FAIL | difficulty 2"}]


def test_a_carried_answer_already_under_the_output_field_is_unchanged():
    row = {"custom_id": "r0", "success": True, "content": {"verdicts": "Q1: PASS"}}

    seen = _run([row], VALIDATOR)

    assert [r.content for r in seen["accumulated"]] == [{"verdicts": "Q1: PASS"}]


def test_a_carried_failure_is_unchanged():
    row = {"custom_id": "r0", "success": False, "content": "provider said no", "error": "boom"}

    seen = _run([row], VALIDATOR)

    assert [(r.content, r.success) for r in seen["accumulated"]] == [("provider said no", False)]


def test_a_json_mode_action_keeps_a_carried_string():
    seen = _run(
        [{"custom_id": "r0", "success": True, "content": "plain"}],
        {**VALIDATOR, "json_mode": True},
    )

    assert [r.content for r in seen["accumulated"]] == ["plain"]
