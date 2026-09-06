"""A batch provider that records what it was actually handed.

Shared by the repair-round tests: asserting on the intermediate row shape proves
nothing, because `BatchTaskPreparator.prepare_tasks` ends by handing the rows to
`provider.prepare_tasks` and returning provider wire format. These assert on the
payload the provider received.
"""

from typing import Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchTask


class RecordingProvider(BaseBatchClient):
    """A real BaseBatchClient whose wire format mirrors OpenAI's."""

    def __init__(self):
        self.submitted: list[dict[str, Any]] = []
        # What this provider reports for any batch id; tests that care set it.
        self.status: str = BatchStatus.COMPLETED

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

    def check_status(self, batch_id):
        return self.status

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
