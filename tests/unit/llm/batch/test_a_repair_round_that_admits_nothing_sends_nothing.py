"""A repair round whose preparation admits no task is not submitted.

`submit_repair_batch` sent whatever preparation admitted, even nothing, so a guard that
turned every record away put an empty batch at the provider. The next pass then found the
round's records unanswered and failed them over the action's `on_exhausted`.
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.preparator import GuardStatus
from agent_actions.llm.batch.services.repair_ops import build_repair_strategy, submit_repair_batch
from agent_actions.llm.providers.batch_base import BatchResult

from .recording_provider import RecordingProvider
from .test_batch_repair_rounds import (
    ACTION,
    CUSTOM_ID,
    FAILING,
    ORIGINAL_PROMPT,
    _agent_config,
    _context_map,
)


def _submit(prepared):
    strategy = build_repair_strategy(_agent_config(repair="auto"))
    failed = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
    strategy.evaluate(failed)
    provider = RecordingProvider()
    provider.submit_batch = MagicMock(wraps=provider.submit_batch)
    with patch(
        "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=prepared
    ):
        result = submit_repair_batch(
            action_indices={ACTION: 0},
            dependency_configs={},
            storage_backend=None,
            provider=provider,
            failed_results=[failed],
            strategy=strategy,
            context_map=_context_map(),
            output_directory="/tmp/test",
            file_name="f.json",
            agent_config=_agent_config(repair="auto"),
            attempt=1,
        )
    return result, provider


class TestARepairRoundThatAdmitsNothing:
    def test_a_guard_that_turns_the_record_away_sends_no_batch(self):
        filtered = MagicMock(guard_status=GuardStatus.FILTERED, passthrough_fields={})

        result, provider = _submit(filtered)

        assert result is None
        provider.submit_batch.assert_not_called()

    def test_a_record_the_guard_admits_still_goes_out(self):
        admitted = MagicMock(
            formatted_prompt=ORIGINAL_PROMPT,
            llm_context={"source": {"text": "the original input"}},
            should_execute=True,
        )

        result, provider = _submit(admitted)

        assert result is not None
        assert result.record_count == len(provider.submitted) == 1
