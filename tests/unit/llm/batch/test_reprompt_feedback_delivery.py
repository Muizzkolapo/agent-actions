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

    def check_status(self, batch_id):  # pragma: no cover - unused here
        return BatchStatus.COMPLETED

    def retrieve_results(self, batch_id, output_directory):  # pragma: no cover - unused here
        return []

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

    from agent_actions.processing.recovery import validation as validation_module

    @reprompt_validation("Every record must carry a non-empty density field.")
    def density_is_present(record: dict) -> bool:
        return bool(record.get("density"))

    yield
    validation_module._VALIDATION_REGISTRY.pop("density_is_present", None)


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

    def test_the_feedback_is_appended_rather_than_replacing_the_prompt(self):
        delivered = _system_message(_submit())
        assert ORIGINAL_PROMPT in delivered
        assert "density" in delivered
        assert delivered.index(ORIGINAL_PROMPT) < delivered.index("density"), (
            "the original instruction must come first, with the feedback after it"
        )


class TestBothResubmissionSitesDeliver:
    """The synchronous loop is the default path via BatchRetryService, so it
    needs its own coverage — dropping the kwarg there left every test green."""

    def test_validate_and_reprompt_also_delivers_the_feedback(self):
        from agent_actions.llm.batch.services import reprompt_ops, resubmission

        provider = RecordingProvider()
        failing = BatchResult(
            custom_id=CUSTOM_ID, content={"wrong_key": "no density"}, success=True
        )
        passing = BatchResult(custom_id=CUSTOM_ID, content={"density": "high"}, success=True)
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

        provider.retrieve_results = lambda batch_id, output_directory: [passing]

        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=prepared,
            ),
            patch.object(
                resubmission, "wait_for_batch_completion", return_value=BatchStatus.COMPLETED
            ),
        ):
            reprompt_ops.validate_and_reprompt(
                action_indices={ACTION: 0},
                dependency_configs={},
                storage_backend=None,
                results=[failing],
                provider=provider,
                context_map=context_map,
                output_directory="/tmp/test",
                file_name="f.json",
                agent_config=AGENT_CONFIG,
            )

        assert provider.submitted, "the synchronous loop submitted nothing"
        delivered = provider.submitted[0]["body"]["messages"][0]["content"]
        assert "density" in delivered, (
            "the synchronous reprompt loop resubmitted without the feedback"
        )


class TestEveryProviderCarriesThePrompt:
    """The prompt a row carries has to survive each provider's own wire format."""

    @pytest.mark.parametrize(
        "module_path, class_name",
        [
            ("agent_actions.llm.providers.openai.batch_client", "OpenAIBatchClient"),
            ("agent_actions.llm.providers.anthropic.batch_client", "AnthropicBatchClient"),
            ("agent_actions.llm.providers.gemini.batch_client", "GeminiBatchClient"),
        ],
    )
    def test_the_prompt_reaches_the_request_body(self, module_path, class_name):
        import importlib
        import json as json_module

        client_cls = getattr(importlib.import_module(module_path), class_name)
        client = client_cls.__new__(client_cls)
        # Constructed without __init__ so no API key is needed; only the
        # attributes format_task_for_provider reads are supplied.
        client.enable_prompt_caching = False
        marker = "FEEDBACK-MARKER-XYZ"
        task = BatchTask(
            custom_id=CUSTOM_ID,
            prompt=f"{ORIGINAL_PROMPT}\n\n{marker}",
            user_content='{"source": {}}',
            model_config={"model_name": "m", "temperature": 0.0, "max_tokens": None},
            metadata={},
        )
        payload = client.format_task_for_provider(task, None)
        assert marker in json_module.dumps(payload), (
            f"{class_name} drops the prompt, so feedback would never reach the model"
        )
