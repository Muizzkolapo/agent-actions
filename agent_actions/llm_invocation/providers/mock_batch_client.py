"""
Mock Batch Client for Testing Retry Functionality.

Simulates batch processing with configurable failure rates.
Use this for manual testing of retry logic without hitting real APIs.

Usage:
    # In your workflow YAML:
    model_vendor: mock
    model_name: mock-model

    # Control failures via environment variables:
    MOCK_BATCH_FAILURE_RATE=0.3  # 30% of records will "fail"
    MOCK_BATCH_FAILURE_IDS=id1,id2,id3  # Specific IDs to fail
    MOCK_BATCH_POLLS_UNTIL_COMPLETE=2  # Number of polls before completion
"""

import os
import uuid
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
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
    failure_ids: Set[str] = field(default_factory=set)


class MockBatchClient(BaseBatchClient):
    """
    Mock batch client for testing retry functionality.

    Simulates batch processing with configurable failures:
    - MOCK_BATCH_FAILURE_RATE: Float 0-1, percentage of records to drop
    - MOCK_BATCH_FAILURE_IDS: Comma-separated list of custom_ids to always fail
    - MOCK_BATCH_POLLS_UNTIL_COMPLETE: Number of status checks before completing

    Example:
        export MOCK_BATCH_FAILURE_RATE=0.2
        export MOCK_BATCH_FAILURE_IDS=record_5,record_10
        agac run my_workflow.yaml --run-mode batch
    """

    # Class-level storage for batch state (simulates server-side storage)
    _batches: Dict[str, MockBatchState] = {}
    _tasks_by_batch: Dict[str, List[Dict[str, Any]]] = {}

    def __init__(
        self,
        failure_rate: Optional[float] = None,
        failure_ids: Optional[Set[str]] = None,
        polls_until_complete: Optional[int] = None,
    ):
        """
        Initialize mock client.

        Args:
            failure_rate: Fraction of records to drop (0-1).
                Env: MOCK_BATCH_FAILURE_RATE
            failure_ids: Specific custom_ids to always fail.
                Env: MOCK_BATCH_FAILURE_IDS
            polls_until_complete: Status checks before completing.
                Env: MOCK_BATCH_POLLS_UNTIL_COMPLETE
        """
        self.failure_rate = failure_rate
        if self.failure_rate is None:
            env_rate = os.environ.get("MOCK_BATCH_FAILURE_RATE", "0")
            self.failure_rate = float(env_rate) if env_rate else 0.0

        self.failure_ids = failure_ids or set()
        if not self.failure_ids:
            env_ids = os.environ.get("MOCK_BATCH_FAILURE_IDS", "")
            if env_ids:
                self.failure_ids = set(env_ids.split(","))

        self.polls_until_complete = polls_until_complete
        if self.polls_until_complete is None:
            env_polls = os.environ.get("MOCK_BATCH_POLLS_UNTIL_COMPLETE", "2")
            self.polls_until_complete = int(env_polls)

        logger.info(
            "MockBatchClient initialized: failure_rate=%.2f, failure_ids=%s, polls=%d",
            self.failure_rate,
            self.failure_ids,
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

            if custom_id in state.failure_ids:
                logger.debug("Simulating failure for %s", custom_id)
                continue  # Skip - simulates missing record

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
            "Mock batch %s: returning %d/%d results (simulated %d failures)",
            batch_id,
            len(lines),
            len(tasks),
            len(state.failure_ids),
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

        # Determine which records will "fail"
        failure_ids = set(self.failure_ids)
        if self.failure_rate > 0:
            for task in tasks:
                if random.random() < self.failure_rate:
                    failure_ids.add(task.get("custom_id", ""))

        # Store state
        state = MockBatchState(
            batch_id=batch_id,
            status="in_progress",
            polls_until_complete=self.polls_until_complete,
            failure_ids=failure_ids,
        )
        self._batches[batch_id] = state
        self._tasks_by_batch[batch_id] = tasks

        logger.info(
            "Mock batch %s submitted: %d tasks, %d will fail",
            batch_id,
            len(tasks),
            len(failure_ids),
        )
        if failure_ids:
            logger.debug("Failing IDs: %s", failure_ids)

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

    @classmethod
    def set_failure_ids_for_batch(cls, batch_id: str, failure_ids: Set[str]) -> None:
        """
        Manually set which IDs should fail for a specific batch.

        Useful for testing specific retry scenarios.
        """
        state = cls._batches.get(batch_id)
        if state:
            state.failure_ids = failure_ids
            logger.debug("Set failure_ids for %s: %s", batch_id, failure_ids)
