"""A `json_mode: false` action gets its batch answer as text under `output_field`, as online does.

The batch clients parse every text answer as JSON. A plain-text action whose answer is JSON text
(a writer that prints a JSON object) became that object, and one whose answer is plain text stayed
a bare string. The expectation loop checks the content against the action's schema before
anything wrapped it, so both failed every repair round: `{questions: ...}` and `"Q1: PASS"` are not
`{raw: ...}` or `{verdicts: ...}`. Online, `call_non_json` wraps the text first (`wrap_non_json`).
"""

from __future__ import annotations

import json
from typing import Any

from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.batch_base import BatchResult

JSON_TEXT = '{"questions": [{"stem": "Which flag?"}]}'
PLAIN_TEXT = "Q1: PASS | difficulty 3"


def _anthropic_line(text: str) -> dict[str, Any]:
    """One line of an Anthropic batch result file: a thinking block, then the text."""
    return {
        "custom_id": "r1",
        "result": {
            "type": "succeeded",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "...", "signature": "sig"},
                    {"type": "text", "text": text},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        },
    }


def _client() -> AnthropicBatchClient:
    return AnthropicBatchClient(api_key="sk-ant-test")


class _Provider:
    """A provider whose results are the parsed Anthropic lines."""

    def __init__(self, *texts: str) -> None:
        self._results = [_client().parse_provider_response(_anthropic_line(t)) for t in texts]

    def retrieve_results(self, batch_id: str, output_directory: str | None) -> list[BatchResult]:
        return self._results


class TestTheParsedResultKeepsTheText:
    def test_json_text_keeps_its_original_text(self):
        result = _client().parse_provider_response(_anthropic_line(JSON_TEXT))

        assert result.raw_text == JSON_TEXT

    def test_plain_text_keeps_its_original_text(self):
        result = _client().parse_provider_response(_anthropic_line(PLAIN_TEXT))

        assert result.raw_text == PLAIN_TEXT


class TestAPlainTextActionGetsTheTextUnderItsOutputField:
    def test_json_text_is_kept_as_text(self):
        (result,) = retrieve_and_reconcile(
            _Provider(JSON_TEXT),
            "b1",
            None,
            agent_config={"json_mode": False, "output_field": "raw"},
        )

        assert result.content == {"raw": JSON_TEXT}

    def test_plain_text_is_wrapped(self):
        (result,) = retrieve_and_reconcile(
            _Provider(PLAIN_TEXT),
            "b1",
            None,
            agent_config={"json_mode": False, "output_field": "verdicts"},
        )

        assert result.content == {"verdicts": PLAIN_TEXT}

    def test_the_default_output_field_is_used_when_none_is_set(self):
        (result,) = retrieve_and_reconcile(
            _Provider(PLAIN_TEXT), "b1", None, agent_config={"json_mode": False}
        )

        assert result.content == {"raw_response": PLAIN_TEXT}


class TestAnAnswerWithNoTextIsNotWrapped:
    def test_a_thinking_only_answer_has_no_text(self):
        line = _anthropic_line("x")
        line["result"]["message"]["content"] = [
            {"type": "thinking", "thinking": "...", "signature": "s"}
        ]
        line["result"]["message"]["stop_reason"] = "max_tokens"

        result = _client().parse_provider_response(line)

        assert result.raw_text is None

    def test_a_thinking_only_answer_still_fails_the_schema_shape(self):
        line = _anthropic_line("x")
        line["result"]["message"]["content"] = [
            {"type": "thinking", "thinking": "...", "signature": "s"}
        ]

        class _ThinkingOnly:
            def retrieve_results(self, batch_id, output_directory):
                return [_client().parse_provider_response(line)]

        (result,) = retrieve_and_reconcile(
            _ThinkingOnly(), "b1", None, agent_config={"json_mode": False, "output_field": "raw"}
        )

        assert not (isinstance(result.content, dict) and "raw" in result.content)

    def test_the_text_null_is_kept_as_text(self):
        (result,) = retrieve_and_reconcile(
            _Provider("null"),
            "b1",
            None,
            agent_config={"json_mode": False, "output_field": "verdicts"},
        )

        assert result.content == {"verdicts": "null"}


class TestStructuredContentWithNoTextIsUnchanged:
    def test_an_object_with_no_text_stays_an_object(self):
        given = BatchResult(custom_id="r1", content={"q": "kept"}, success=True)

        class _Objects:
            def retrieve_results(self, batch_id, output_directory):
                return [given]

        (result,) = retrieve_and_reconcile(
            _Objects(), "b1", None, agent_config={"json_mode": False, "output_field": "raw"}
        )

        assert result.content == {"q": "kept"}


class TestAJsonActionIsUnchanged:
    def test_json_mode_keeps_the_parsed_object(self):
        (result,) = retrieve_and_reconcile(
            _Provider(JSON_TEXT), "b1", None, agent_config={"json_mode": True}
        )

        assert result.content == json.loads(JSON_TEXT)

    def test_no_config_keeps_the_parsed_object(self):
        (result,) = retrieve_and_reconcile(_Provider(JSON_TEXT), "b1", None)

        assert result.content == json.loads(JSON_TEXT)

    def test_a_failed_result_is_unchanged(self):
        failed = BatchResult(custom_id="r1", content=None, success=False, error="overloaded")

        class _Failed:
            def retrieve_results(self, batch_id, output_directory):
                return [failed]

        (result,) = retrieve_and_reconcile(
            _Failed(), "b1", None, agent_config={"json_mode": False, "output_field": "raw"}
        )

        assert result.content is None and result.error == "overloaded"


# ---------------------------------------------------------------------------
# The schema check the repair loop runs, a recovery round, an earlier state, the CLI
# ---------------------------------------------------------------------------

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


class TestTheRepairLoopSchemaCheckPassesTheText:
    def _passes(self, result: BatchResult) -> bool:
        from agent_actions.llm.batch.services.repair_ops import build_repair_strategy

        return build_repair_strategy(VALIDATOR).evaluate(result).passed

    def test_the_unwrapped_answer_fails_the_check(self):
        """The bug: what the loop checked before the fix."""
        result = _client().parse_provider_response(_anthropic_line(PLAIN_TEXT))

        assert not self._passes(result)

    def test_the_answer_retrieval_wraps_passes_the_check(self):
        (result,) = retrieve_and_reconcile(
            _Provider(PLAIN_TEXT), "b1", None, agent_config=VALIDATOR
        )

        assert self._passes(result)


class TestAToolAnswerHasNoText:
    def test_a_tool_answer_has_no_text(self):
        line = _anthropic_line("x")
        line["result"]["message"]["content"] = [
            {"type": "tool_use", "id": "t1", "name": "out", "input": {"verdicts": "Q1: PASS"}}
        ]

        result = _client().parse_provider_response(line)

        assert result.content == {"verdicts": "Q1: PASS"} and result.raw_text is None


class TestAStateAnEarlierVersionWrote:
    """An earlier version persisted the parsed content and no text, and no `text_kept` marker."""

    def _restore(self, **row):
        from agent_actions.llm.batch.services.retry_serialization import deserialize_results

        return deserialize_results([{"custom_id": "r1", "success": True, **row}])[0]

    def test_parsed_json_text_gets_its_text_back(self):
        result = self._restore(content={"questions": [{"stem": "Which flag?"}]})

        assert json.loads(result.raw_text) == {"questions": [{"stem": "Which flag?"}]}

    def test_plain_text_gets_its_text_back(self):
        assert self._restore(content=PLAIN_TEXT).raw_text == PLAIN_TEXT

    def test_a_state_this_version_wrote_keeps_no_text_it_did_not_have(self):
        result = self._restore(content={"q": "kept"}, text_kept=True)

        assert result.raw_text is None

    def test_this_version_marks_every_result(self):
        from agent_actions.llm.batch.services.retry_serialization import serialize_results

        (row,) = serialize_results([BatchResult(custom_id="r1", content={"q": 1}, success=True)])

        assert row["text_kept"] is True


class TestARecoveryRoundWrapsWhatItCarries:
    """`process_recovery_batch`: the retrieved round and the results carried from the state."""

    def _run(self, accumulated_rows):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from agent_actions.llm.batch.core.batch_models import BatchJobEntry, RecoveryType
        from agent_actions.llm.batch.services import processing_recovery as pr

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
        seen = {}

        def handler(context, identity, *, state, recovery_results, accumulated, context_map):
            seen["recovery"], seen["accumulated"] = recovery_results, accumulated
            return "done"

        state = SimpleNamespace(accumulated_results=accumulated_rows)
        with (
            patch.object(pr.RecoveryStateManager, "load", return_value=state),
            patch.object(pr, "handle_repair_recovery", handler),
        ):
            pr.process_recovery_batch(
                service, "b2", "f.json_repair_1", entry, "/tmp/out", dict(VALIDATOR), MagicMock()
            )
        return seen

    def test_the_retrieved_round_is_wrapped(self):
        seen = self._run([])

        assert [r.content for r in seen["recovery"]] == [{"verdicts": PLAIN_TEXT}]

    def test_a_carried_result_from_an_earlier_state_is_wrapped(self):
        seen = self._run(
            [{"custom_id": "r0", "success": True, "content": "Q1: FAIL | difficulty 2"}]
        )

        assert [r.content for r in seen["accumulated"]] == [{"verdicts": "Q1: FAIL | difficulty 2"}]

    def test_a_carried_result_this_version_wrapped_is_unchanged(self):
        row = {
            "custom_id": "r0",
            "success": True,
            "content": {"verdicts": "Q1: PASS"},
            "raw_text": "Q1: PASS",
            "text_kept": True,
        }

        seen = self._run([row])

        assert [r.content for r in seen["accumulated"]] == [{"verdicts": "Q1: PASS"}]


class TestBatchRetrieveWritesTheText:
    def _service(self, provider):
        from unittest.mock import MagicMock

        from agent_actions.llm.batch.services.retrieval import BatchRetrievalService

        resolver = MagicMock()
        resolver.get_for_batch_id.return_value = provider
        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = None
        return BatchRetrievalService(
            client_resolver=resolver,
            context_manager=MagicMock(),
            registry_manager_factory=lambda name: manager,
            action_name="validate",
        )

    def _written(self, path) -> Any:
        row = json.loads(path.read_text().splitlines()[0])
        return json.loads(row["response"]["body"]["choices"][0]["message"]["content"])

    def test_the_action_config_wraps_the_written_text(self, tmp_path):
        path = self._service(_Provider(PLAIN_TEXT)).retrieve_results(
            "b1", str(tmp_path), agent_config=VALIDATOR
        )

        assert self._written(path) == {"verdicts": PLAIN_TEXT}

    def test_the_cli_reads_the_action_config(self, monkeypatch):
        from agent_actions.llm.batch import batch_cli

        class _Inspector:
            def __init__(self, *args, **kwargs):
                pass

            def load(self):
                return {"validate": VALIDATOR}

        monkeypatch.setattr(
            "agent_actions.services.workflow_inspector.WorkflowInspector", _Inspector
        )
        monkeypatch.setattr(batch_cli, "resolve_project_root", lambda root: root)

        assert batch_cli._action_config(None, "wf", "validate") is VALIDATOR

    def test_the_cli_warns_and_goes_on_when_the_config_does_not_load(self, monkeypatch, capsys):
        from agent_actions.llm.batch import batch_cli

        class _Broken:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("no config")

        monkeypatch.setattr("agent_actions.services.workflow_inspector.WorkflowInspector", _Broken)
        monkeypatch.setattr(batch_cli, "resolve_project_root", lambda root: root)

        assert batch_cli._action_config(None, "wf", "validate") is None
        assert "could not load the config of wf" in capsys.readouterr().err
