"""
Mock Batch Client for Testing.

Provides a simple mock batch client for testing batch processing
without hitting real APIs. Uses schema-based fake data generation.

Auto-completes after configurable time (default 5 seconds).
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.llm.providers.batch_base import (
    BaseBatchClient,
    BatchTask,
)

logger = logging.getLogger(__name__)


@dataclass
class MockBatchState:
    """Tracks state of a mock batch job."""

    batch_id: str
    tasks: list[BatchTask] = field(default_factory=list)
    status: str = "in_progress"
    poll_count: int = 0
    polls_until_complete: int = 0
    created_at: float = field(default_factory=time.time)
    complete_after_seconds: float = 5.0  # Auto-complete after 5 seconds


class AgacBatchClient(BaseBatchClient):
    """
    Mock batch client for testing batch processing without real APIs.

    Auto-completes batches after a configurable time (default 5 seconds).

    Configuration:
    - AGAC_BATCH_COMPLETE_AFTER_SECONDS: Time before auto-complete (default: 5)
    - AGAC_BATCH_POLLS_UNTIL_COMPLETE: Poll count before complete (default: 0, disabled)

    Example:
        # Complete after 10 seconds
        export AGAC_BATCH_COMPLETE_AFTER_SECONDS=10
        agac run my_workflow.yaml --run-mode batch
    """

    # Class-level storage for batch state (persists across CLI runs via disk)
    _batches: dict[str, MockBatchState] = {}
    _tasks_by_batch: dict[str, list[dict[str, Any]]] = {}

    def __init__(
        self,
        polls_until_complete: int | None = None,
        complete_after_seconds: float | None = None,
        **kwargs,
    ):
        """
        Initialize mock client.

        Args:
            polls_until_complete: Status checks before completing (default: 0, disabled)
            complete_after_seconds: Seconds before auto-complete (default: 5)
            **kwargs: Ignored for backward compatibility
        """
        import os

        # Poll-based completion (default disabled)
        self.polls_until_complete = polls_until_complete
        if self.polls_until_complete is None:
            env_polls = os.environ.get("AGAC_BATCH_POLLS_UNTIL_COMPLETE", "0")
            self.polls_until_complete = int(env_polls)

        # Time-based completion (default 5 seconds)
        self.complete_after_seconds = complete_after_seconds
        if self.complete_after_seconds is None:
            env_seconds = os.environ.get("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "5")
            self.complete_after_seconds = float(env_seconds)

        logger.info(
            "AgacBatchClient initialized: polls=%d, complete_after=%.1fs",
            self.polls_until_complete,
            self.complete_after_seconds,
        )

    # ========== Required abstract method implementations ==========

    def _get_default_model(self) -> str:
        """Return default model name."""
        return "agac-model"

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Format task for mock processing."""
        return {
            "custom_id": batch_task.custom_id,
            "prompt": batch_task.prompt,
            "user_content": batch_task.user_content,
            "model_config": batch_task.model_config,
            "schema": schema,
        }

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from mock state with time-based auto-completion."""
        state = self._batches.get(batch_id)
        if not state:
            return "unknown"

        state.poll_count += 1

        elapsed = time.time() - state.created_at
        if elapsed >= state.complete_after_seconds:
            state.status = "completed"
            logger.debug(
                "Mock batch %s auto-completed after %.1fs",
                batch_id,
                elapsed,
            )
        elif state.polls_until_complete > 0 and state.poll_count >= state.polls_until_complete:
            state.status = "completed"
            logger.debug(
                "Mock batch %s completed after %d polls",
                batch_id,
                state.poll_count,
            )
        else:
            remaining = state.complete_after_seconds - elapsed
            logger.debug(
                "Mock batch %s status: %s (poll %d, %.1fs remaining)",
                batch_id,
                state.status,
                state.poll_count,
                remaining,
            )

        return state.status

    def _normalize_status(self, raw_status: str) -> str:
        """Status is already normalized."""
        return raw_status

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Generate mock results as JSONL bytes using schema-based fake data."""
        state = self._batches.get(batch_id)
        if not state:
            raise ValueError(f"Batch {batch_id} not found")

        tasks = self._tasks_by_batch.get(batch_id, [])
        lines = []

        for task in tasks:
            custom_id = task.get("custom_id", "unknown")
            body = task.get("body", {})

            # Track attempt for this custom_id (for reprompt testing)
            attempt = self._get_attempt_for_custom_id(custom_id)

            # Generate fake data using schema from request
            openai_response = FakeDataGenerator.generate_openai_response(custom_id, body, attempt)

            # Wrap in batch result format
            result = {
                "id": f"batch_req_{uuid.uuid4().hex[:24]}",
                "custom_id": custom_id,
                "response": {
                    "status_code": 200,
                    "body": openai_response,
                },
                "error": None,
            }

            lines.append(json.dumps(result))

        logger.info(
            "Mock batch %s: returning %d results",
            batch_id,
            len(lines),
        )

        return "\n".join(lines).encode("utf-8")

    def _get_attempt_for_custom_id(self, custom_id: str) -> int:
        """
        Track attempt count per custom_id across batch resubmissions.

        Args:
            custom_id: Custom ID to track

        Returns:
            Current attempt number (1-indexed)
        """
        if not hasattr(self, "_custom_id_attempts"):
            self._custom_id_attempts: dict[str, int] = {}

        if custom_id not in self._custom_id_attempts:
            self._custom_id_attempts[custom_id] = 1
        else:
            self._custom_id_attempts[custom_id] += 1

        return self._custom_id_attempts[custom_id]

    def _get_result_file_name(self, batch_id: str) -> str:
        """Get result file name."""
        return f"{batch_id}_mock_results.jsonl"

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to input file."""
        return self._write_jsonl_file(tasks, batch_dir, batch_name, "mock")

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Submit mock batch job."""
        batch_id = f"mock_batch_{uuid.uuid4().hex[:12]}"

        # Read tasks from input file
        tasks = []
        with open(input_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))

        # Store state
        state = MockBatchState(
            batch_id=batch_id,
            status="in_progress",
            polls_until_complete=self.polls_until_complete,  # type: ignore[arg-type]
            complete_after_seconds=self.complete_after_seconds,  # type: ignore[arg-type]
        )
        self._batches[batch_id] = state
        self._tasks_by_batch[batch_id] = tasks

        logger.info(
            "Mock batch %s submitted: %d tasks",
            batch_id,
            len(tasks),
        )

        return batch_id, "in_progress"

    def _extract_error_from_response(self, raw_response: Any) -> str | None:
        """Check for error in response."""
        if isinstance(raw_response, dict):
            error = raw_response.get("error")
            if error:
                return str(error.get("message", error))
        return None

    def _extract_content_from_response(self, raw_response: Any) -> Any:
        """Extract content from mock response."""
        if isinstance(raw_response, dict):
            response = raw_response.get("response", {})
            body = response.get("body", {})
            choices = body.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")
        return ""

    def _extract_metadata_from_response(self, raw_response: Any) -> dict[str, Any]:
        """Extract metadata from response."""
        metadata = {}
        if isinstance(raw_response, dict):
            response = raw_response.get("response", {})
            body = response.get("body", {})
            metadata["model"] = body.get("model", "agac-model")
            choices = body.get("choices", [])
            if choices:
                metadata["finish_reason"] = choices[0].get("finish_reason", "stop")
        return metadata

    def _extract_usage_from_response(self, raw_response: Any) -> dict[str, Any] | None:
        """Extract usage info from response."""
        if isinstance(raw_response, dict):
            response = raw_response.get("response", {})
            body = response.get("body", {})
            return body.get("usage")  # type: ignore[no-any-return]
        return None

    # ========== Test utilities ==========

    @classmethod
    def reset(cls):
        """Reset all mock batch state. Useful between tests."""
        cls._batches.clear()
        cls._tasks_by_batch.clear()
        logger.debug("AgacBatchClient state reset")

    @classmethod
    def get_batch_state(cls, batch_id: str) -> MockBatchState | None:
        """Get internal state of a batch (for testing/debugging)."""
        return cls._batches.get(batch_id)
