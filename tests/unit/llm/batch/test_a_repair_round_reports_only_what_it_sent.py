"""A repair round reports as sent only the records preparation admitted.

With two failing records, a guard that turns one away at preparation left it in
`sent_ids`. When the round came back, the record read as one the provider dropped and
was failed as such, instead of being given up under the action's `on_exhausted`.
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.preparator import GuardStatus
from agent_actions.llm.batch.services.repair_ops import build_repair_strategy, submit_repair_batch
from agent_actions.llm.providers.batch_base import BatchResult

from .recording_provider import RecordingProvider
from .test_batch_repair_rounds import ACTION, FAILING, ORIGINAL_PROMPT, _agent_config

ADMITTED_ID = "t-001"
FILTERED_ID = "t-002"


def _context_map():
    return {
        cid: {
            "target_id": cid,
            "source_guid": f"sg-{cid}",
            "content": {"source": {"text": f"input {cid}"}},
        }
        for cid in (ADMITTED_ID, FILTERED_ID)
    }


def _prepare(item, *_args, **_kwargs):
    if item["target_id"] == FILTERED_ID:
        return MagicMock(guard_status=GuardStatus.FILTERED, passthrough_fields={})
    return MagicMock(
        formatted_prompt=ORIGINAL_PROMPT,
        llm_context={"source": {"text": "the original input"}},
        should_execute=True,
    )


def test_sent_ids_name_only_the_admitted_record():
    strategy = build_repair_strategy(_agent_config(repair="auto"))
    failed = [BatchResult(custom_id=cid, content=FAILING, success=True) for cid in _context_map()]
    for result in failed:
        strategy.evaluate(result)
    provider = RecordingProvider()
    with patch("agent_actions.processing.task_preparer.TaskPreparer.prepare", side_effect=_prepare):
        submission = submit_repair_batch(
            action_indices={ACTION: 0},
            dependency_configs={},
            storage_backend=None,
            provider=provider,
            failed_results=failed,
            strategy=strategy,
            context_map=_context_map(),
            output_directory="/tmp/test",
            file_name="f.json",
            agent_config=_agent_config(repair="auto"),
            attempt=1,
        )

    assert submission is not None
    assert submission.record_count == len(provider.submitted) == 1
    assert submission.sent_ids == [ADMITTED_ID]


class TestTheRecordAGuardTurnsAwayIsGivenUp:
    """Through `check_and_submit_repair`: the admitted record is sent, the other ends here."""

    def _submit(self, **expect):
        from agent_actions.llm.batch.services import processing_recovery as pr

        from .test_repair_deferral import _Backend, _context, _identity, _state

        config = _agent_config(repair="auto", **expect)
        failed = [
            BatchResult(custom_id=cid, content=FAILING, success=True) for cid in _context_map()
        ]
        backend = _Backend()
        context = _context(RecordingProvider(), backend, config)
        with patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare", side_effect=_prepare
        ):
            should_continue = pr.check_and_submit_repair(
                context,
                _identity(),
                batch_results=failed,
                context_map=_context_map(),
                recovery_state=None,
            )
        return should_continue, failed, _state(backend), context

    def test_the_round_waits_on_the_admitted_record_alone(self):
        should_continue, _failed, state, _context = self._submit()

        assert should_continue is False
        assert state.repair_submitted_ids == [ADMITTED_ID]

    def test_the_turned_away_record_is_exhausted_and_carried_to_the_output(self):
        _should, failed, state, _context = self._submit()

        turned_away = next(r for r in failed if r.custom_id == FILTERED_ID)
        assert turned_away.recovery_metadata.expectations.failed == ["enough_options"]
        assert [r["custom_id"] for r in state.graduated_results] == [FILTERED_ID]

    def test_on_exhausted_raise_parks_the_halt_the_pass_raises_after_deferring(self):
        from agent_actions.expectations.service import ExpectationsExhaustedError

        _should, _failed, _state, context = self._submit(on_exhausted="raise")

        assert isinstance(context.pending_exhaustion, ExpectationsExhaustedError)
