"""A batch repair round stores, as its prompt trace, the prompt it sent.

The row is written while each record is prepared, before the round's feedback is
appended to the prompt, so the stored prompt lacked the feedback the provider got.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

FEEDBACK = "## Your previous output failed validation\nsummary_ok: the summary is empty"


def _agent_config() -> dict:
    return {
        "agent_type": "summarize",
        "action_name": "summarize",
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "json_mode": False,
        "granularity": "record",
        "context_scope": {"observe": ["source.page_content"]},
    }


def _round(attempt: int, feedback_by_id: dict[str, str] | None) -> tuple[dict, str]:
    """Run one round; return the stored prompt per (record, attempt) and the prompt sent."""
    stored: dict[tuple[str, int], str] = {}
    store = MagicMock()
    store.write_prompt_trace.side_effect = lambda **row: stored.__setitem__(
        (row["record_id"], row["attempt"]), row["compiled_prompt"]
    )
    provider = MagicMock()
    provider.prepare_tasks.return_value = []
    preparator = BatchTaskPreparator(
        action_indices={}, dependency_configs={}, storage_backend=store
    )
    data = [{"target_id": "t1", "source_guid": "sg1", "content": {"page_content": "alpha"}}]

    with patch(
        "agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt", return_value="Summarise."
    ):
        preparator.prepare_tasks(
            agent_config=_agent_config(),
            data=data,
            provider=provider,
            output_directory="/tmp/test",
            attempt=attempt,
            feedback_by_id=feedback_by_id,
        )
    (sent_task,) = provider.prepare_tasks.call_args.args[0]
    return stored, sent_task["prompt"]


def test_a_repair_round_stores_the_prompt_with_its_feedback():
    stored, sent = _round(attempt=1, feedback_by_id={"t1": FEEDBACK})

    assert sent.endswith(FEEDBACK)
    assert stored[("t1", 1)] == sent


def test_a_first_round_with_no_feedback_stores_the_prompt_unchanged():
    stored, sent = _round(attempt=0, feedback_by_id=None)

    assert FEEDBACK not in sent
    assert stored[("t1", 0)] == sent
