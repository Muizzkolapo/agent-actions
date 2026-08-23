"""Reprompt feedback must reach the request the provider actually receives.

Batch reprompt resubmits only the records that failed validation, and the whole
point of resubmitting is that the model is told what was wrong. The feedback has
to survive `BatchTaskPreparator.prepare_tasks`, which ends by handing the rows to
`provider.prepare_tasks` and returning provider wire format — so asserting on the
intermediate row shape proves nothing. These tests assert on the provider payload.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.services.reprompt_ops import submit_reprompt_batch
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult, BatchTask
from agent_actions.processing.recovery.validation import reprompt_validation

ACTION = "assess"
CUSTOM_ID = "t-001"
ORIGINAL_PROMPT = "ORIGINAL PROMPT"

AGENT_CONFIG: dict[str, Any] = {
    "name": ACTION,
    "action_name": ACTION,
    "agent_type": ACTION,
    # json_mode off keeps the fixture focused on prompt delivery, not schema compilation.
    "json_mode": False,
    "model_name": "test-model",
    "prompt": ORIGINAL_PROMPT,
    "reprompt": {
        "validation": "density_is_present",
        "max_attempts": 2,
        "on_schema_mismatch": "reprompt",
    },
}


class RecordingProvider(BaseBatchClient):
    """A real BaseBatchClient whose wire format mirrors OpenAI's."""

    def __init__(self):
        self.submitted: list[dict[str, Any]] = []

    def _get_default_model(self) -> str:
        return "test-model"

    def _get_default_temperature(self) -> float:
        return 0.0

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "custom_id": batch_task.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": batch_task.model_config["model_name"],
                "messages": [
                    {"role": "system", "content": batch_task.prompt},
                    {"role": "user", "content": batch_task.user_content},
                ],
            },
        }

    def submit_batch(self, tasks, batch_name, output_directory):
        self.submitted = tasks
        return "batch-1", BatchStatus.SUBMITTED

    def check_batch_status(self, batch_id):  # pragma: no cover - unused here
        return BatchStatus.COMPLETED

    def retrieve_results(self, batch_id, output_directory):  # pragma: no cover - unused here
        return []

    def cancel_batch(self, batch_id):  # pragma: no cover - unused here
        return True

    # Abstract surface this test never exercises.
    def _submit_to_provider_api(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _prepare_batch_input_file(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _fetch_status(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _normalize_status(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _fetch_raw_results(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _get_result_file_name(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _extract_content_from_response(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _extract_error_from_response(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _extract_metadata_from_response(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _extract_usage_from_response(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _registered_validation():
    """Register at call time, not import time — the registry is process-global."""

    @reprompt_validation("Every record must carry a non-empty density field.")
    def density_is_present(record: dict) -> bool:
        return bool(record.get("density"))

    yield


def _submit() -> RecordingProvider:
    """Run one reprompt submission through the real preparation pipeline."""
    provider = RecordingProvider()
    failed = BatchResult(
        custom_id=CUSTOM_ID,
        content={"wrong_key": "does not match"},
        success=True,
    )
    context_map = {
        CUSTOM_ID: {
            "target_id": CUSTOM_ID,
            "source_guid": "sg-1",
            "content": {"source": {"text": "the original input"}},
        }
    }

    prepared = MagicMock()
    prepared.formatted_prompt = ORIGINAL_PROMPT
    prepared.llm_context = {"source": {"text": "the original input"}}
    prepared.should_execute = True

    # Only prompt rendering is stubbed; provider conversion runs for real.
    with patch(
        "agent_actions.processing.task_preparer.TaskPreparer.prepare",
        return_value=prepared,
    ):
        submit_reprompt_batch(
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
    return provider


def _system_message(provider: RecordingProvider) -> str:
    assert provider.submitted, "nothing was submitted to the provider"
    return provider.submitted[0]["body"]["messages"][0]["content"]


class TestFeedbackReachesTheProvider:
    def test_the_submitted_request_is_not_the_original_prompt(self):
        delivered = _system_message(_submit())
        assert delivered != ORIGINAL_PROMPT, (
            "the provider received a byte-identical prompt — the feedback was "
            "dropped, so this is a re-roll, not a reprompt"
        )

    def test_the_submitted_request_names_what_failed(self):
        assert "density" in _system_message(_submit()), (
            "the model is told to retry without being told what was wrong"
        )

    def test_the_original_prompt_survives_alongside_the_feedback(self):
        assert ORIGINAL_PROMPT in _system_message(_submit())
