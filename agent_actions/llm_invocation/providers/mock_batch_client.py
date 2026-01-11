"""
Mock Batch Client for Testing.

Provides a simple mock batch client for testing batch processing
without hitting real APIs.
"""

import uuid
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from agent_actions.llm_invocation.providers.batch_client_base import (
    BaseBatchClient,
    BatchTask,
)

logger = logging.getLogger(__name__)


@dataclass
class MockBatchState:
    """Tracks state of a mock batch job."""

    batch_id: str
    tasks: List[BatchTask] = field(default_factory=list)
    status: str = "in_progress"
    poll_count: int = 0
    polls_until_complete: int = 2


class MockBatchClient(BaseBatchClient):
    """
    Mock batch client for testing batch processing without real APIs.

    Configuration:
    - MOCK_BATCH_POLLS_UNTIL_COMPLETE: Number of status checks before completing (default: 2)

    Example:
        export MOCK_BATCH_POLLS_UNTIL_COMPLETE=3
        agac run my_workflow.yaml --run-mode batch
    """

    # Class-level storage for batch state (simulates server-side storage)
    _batches: Dict[str, MockBatchState] = {}
    _tasks_by_batch: Dict[str, List[Dict[str, Any]]] = {}

    def __init__(self, polls_until_complete: Optional[int] = None, **kwargs):
        """
        Initialize mock client.

        Args:
            polls_until_complete: Status checks before completing (default: 2)
            **kwargs: Ignored for backward compatibility
        """
        import os

        self.polls_until_complete = polls_until_complete
        if self.polls_until_complete is None:
            env_polls = os.environ.get("MOCK_BATCH_POLLS_UNTIL_COMPLETE", "2")
            self.polls_until_complete = int(env_polls)

        logger.info(
            "MockBatchClient initialized: polls=%d",
            self.polls_until_complete,
        )

    # ========== Required abstract method implementations ==========

    def _get_default_model(self) -> str:
        """Return default model name."""
        return "mock-model"

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Format task for mock processing."""
        return {
            "custom_id": batch_task.custom_id,
            "prompt": batch_task.prompt,
            "user_content": batch_task.user_content,
            "model_config": batch_task.model_config,
            "schema": schema,
        }

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from mock state."""
        state = self._batches.get(batch_id)
        if not state:
            return "unknown"

        state.poll_count += 1
        if state.poll_count >= state.polls_until_complete:
            state.status = "completed"

        logger.debug(
            "Mock batch %s status: %s (poll %d/%d)",
            batch_id,
            state.status,
            state.poll_count,
            state.polls_until_complete,
        )
        return state.status

    def _normalize_status(self, raw_status: str) -> str:
        """Status is already normalized."""
        return raw_status

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Generate mock results as JSONL bytes."""
        state = self._batches.get(batch_id)
        if not state:
            raise ValueError(f"Batch {batch_id} not found")

        tasks = self._tasks_by_batch.get(batch_id, [])
        lines = []

        for task in tasks:
            custom_id = task.get("custom_id", "unknown")

            # Generate mock successful response
            result = {
                "custom_id": custom_id,
                "response": {
                    "body": {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "mock_response": True,
                                            "original_id": custom_id,
                                            "batch_id": batch_id,
                                        }
                                    )
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                        "model": "mock-model",
                    }
                },
            }
            lines.append(json.dumps(result))

        logger.info(
            "Mock batch %s: returning %d results",
            batch_id,
            len(lines),
        )

        return "\n".join(lines).encode("utf-8")

    def _get_result_file_name(self, batch_id: str) -> str:
        """Get result file name."""
        return f"{batch_id}_mock_results.jsonl"

    def _prepare_batch_input_file(
        self, tasks: List[Dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to input file."""
        return self._write_jsonl_file(tasks, batch_dir, batch_name, "mock")

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> Tuple[str, str]:
        """Submit mock batch job."""
        batch_id = f"mock_batch_{uuid.uuid4().hex[:12]}"

        # Read tasks from input file
        tasks = []
        with open(input_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))

        # Store state
        state = MockBatchState(
            batch_id=batch_id,
            status="in_progress",
            polls_until_complete=self.polls_until_complete,
        )
        self._batches[batch_id] = state
        self._tasks_by_batch[batch_id] = tasks

        logger.info(
            "Mock batch %s submitted: %d tasks",
            batch_id,
            len(tasks),
        )

        return batch_id, "in_progress"

    def _extract_error_from_response(self, raw_response: Any) -> Optional[str]:
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

    def _extract_metadata_from_response(self, raw_response: Any) -> Dict[str, Any]:
        """Extract metadata from response."""
        metadata = {}
        if isinstance(raw_response, dict):
            response = raw_response.get("response", {})
            body = response.get("body", {})
            metadata["model"] = body.get("model", "mock-model")
            choices = body.get("choices", [])
            if choices:
                metadata["finish_reason"] = choices[0].get("finish_reason", "stop")
        return metadata

    def _extract_usage_from_response(self, raw_response: Any) -> Optional[Dict[str, Any]]:
        """Extract usage info from response."""
        if isinstance(raw_response, dict):
            response = raw_response.get("response", {})
            body = response.get("body", {})
            return body.get("usage")
        return None

    # ========== Test utilities ==========

    @classmethod
    def reset(cls):
        """Reset all mock batch state. Useful between tests."""
        cls._batches.clear()
        cls._tasks_by_batch.clear()
        logger.debug("MockBatchClient state reset")

    @classmethod
    def get_batch_state(cls, batch_id: str) -> Optional[MockBatchState]:
        """Get internal state of a batch (for testing/debugging)."""
        return cls._batches.get(batch_id)
