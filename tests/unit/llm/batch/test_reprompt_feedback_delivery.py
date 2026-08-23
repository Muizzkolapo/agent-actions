"""Reprompt feedback must actually reach the resubmitted batch.

Batch reprompt resubmits only the records that failed validation, and the
whole point of resubmitting is that the model is told what was wrong. The
feedback has to survive task preparation and land on something the provider
sends — otherwise the retry re-sends the identical prompt and reprompt
degrades into a plain re-roll.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import (
    BatchTaskPreparationStats,
    PreparedBatchTasks,
)
from agent_actions.llm.batch.services.reprompt_ops import submit_reprompt_batch
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.recovery.validation import reprompt_validation

ACTION = "assess"
CUSTOM_ID = "t-001"

AGENT_CONFIG: dict[str, Any] = {
    "name": ACTION,
    "action_name": ACTION,
    "json_mode": True,
    "reprompt": {
        "validation": "density_is_present",
        "max_attempts": 2,
        "on_schema_mismatch": "reprompt",
    },
    "schema": {
        "type": "object",
        "properties": {"density": {"type": "string"}},
        "required": ["density"],
        "additionalProperties": False,
    },
}

# What the provider actually receives is built from these keys.
PREPARED_TASK = {
    "target_id": CUSTOM_ID,
    "content": {"source": {"text": "the original input"}},
    "prompt": "ORIGINAL PROMPT",
}


@reprompt_validation("Every record must carry a non-empty density field.")
def density_is_present(record: dict) -> bool:
    return bool(record.get("density"))


def _submit(capture: dict[str, Any]):
    """Run submit_reprompt_batch with preparation and submission mocked."""
    provider = MagicMock()

    def fake_submit(tasks, batch_name, output_directory):
        capture["tasks"] = tasks
        return "batch-1", BatchStatus.SUBMITTED

    provider.submit_batch.side_effect = fake_submit

    failed = BatchResult(
        custom_id=CUSTOM_ID,
        content={"wrong_key": "does not match the schema"},
        success=True,
    )
    context_map = {CUSTOM_ID: {"target_id": CUSTOM_ID, "content": {}, "source_guid": "sg-1"}}

    prepared = PreparedBatchTasks(
        tasks=[dict(PREPARED_TASK)],
        context_map=context_map,
        stats=BatchTaskPreparationStats(),
    )

    with patch(
        "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator.prepare_tasks",
        return_value=prepared,
    ):
        return submit_reprompt_batch(
            action_indices={ACTION: 0},
            dependency_configs={},
            storage_backend=None,
            provider=provider,
            failed_results=[failed],
            context_map=context_map,
            output_directory="/tmp/test",
            file_name="f.json",
            agent_config=AGENT_CONFIG,
            attempt=1,
        )


class TestFeedbackReachesTheProvider:
    def test_the_resubmitted_task_carries_the_validation_feedback(self):
        capture: dict[str, Any] = {}
        _submit(capture)
        tasks = capture.get("tasks")
        assert tasks, "nothing was submitted"
        delivered = tasks[0]["prompt"]
        assert delivered != PREPARED_TASK["prompt"], (
            "the resubmitted prompt is byte-identical to the original — the "
            "feedback was dropped, so this is a re-roll, not a reprompt"
        )

    def test_the_feedback_names_the_field_that_failed(self):
        capture: dict[str, Any] = {}
        _submit(capture)
        delivered = capture["tasks"][0]["prompt"]
        assert "density" in delivered, (
            "the model is told to retry without being told what was wrong"
        )

    def test_the_original_prompt_is_preserved_alongside_the_feedback(self):
        capture: dict[str, Any] = {}
        _submit(capture)
        assert "ORIGINAL PROMPT" in capture["tasks"][0]["prompt"]
