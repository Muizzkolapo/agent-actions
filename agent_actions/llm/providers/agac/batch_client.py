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

from agent_actions.config.paths import PathManagerError
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

    # In-process cache. The durable copy is on disk, because a batch workflow
    # spans two runs by design: submitting pauses and asks to be run again, and
    # that is a new process with an empty cache.
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

    @staticmethod
    def _state_dir() -> Path:
        """Where a submitted batch is recorded, derivable without any argument.

        The resume path is given a batch id and nothing else — it never asks for
        a batch directory — so the location cannot depend on the output directory
        the submit happened to use.

        From the project root the CLI resolved, not the working directory: `agac`
        supports being run from a subdirectory and does not chdir, so a cwd-derived
        path would lose the batch exactly as this exists to prevent. Not under
        `agent_io/`, which is per-workflow and which the docs scanner treats as
        marking one — a copy at the project root would make it report a workflow
        named after the project.
        """
        from agent_actions.utils.path_utils import ensure_directory_exists, get_path_manager

        state_dir = get_path_manager().get_project_root() / ".agac" / "batch_state"
        ensure_directory_exists(state_dir)
        return state_dir

    @classmethod
    def _write_state(cls, state: MockBatchState, tasks: list[dict[str, Any]]) -> None:
        """Record a submitted batch where the next run can find it.

        Written atomically: a truncated file reads back as no batch at all, which
        is the failure this exists to prevent, arrived at silently.
        """
        from agent_actions.utils.atomic_write import atomic_json_write

        atomic_json_write(
            cls._state_dir() / f"{state.batch_id}.json",
            # Reconstructible by definition, and rewritten on every poll: durability
            # here would buy nothing and cost an fsync per status check.
            {
                "batch_id": state.batch_id,
                "status": state.status,
                "poll_count": state.poll_count,
                "polls_until_complete": state.polls_until_complete,
                "created_at": state.created_at,
                "complete_after_seconds": state.complete_after_seconds,
                "tasks": tasks,
            },
            fsync=False,
        )

    @classmethod
    def _forget_state(cls, batch_id: str) -> None:
        """Drop a batch's record.

        Deliberately not called when results are read. A read hands bytes to a
        caller that still has to write, parse, reconcile and evaluate them, and
        any of that can fail with the entry already marked done — so a re-run
        comes back for the same batch. Forgetting it there turns a repeatable
        read into `Batch not found`, which is worse than the status this exists
        to fix. Whose job it is to end the record's life is open.
        """
        (cls._state_dir() / f"{batch_id}.json").unlink(missing_ok=True)
        cls._batches.pop(batch_id, None)
        cls._tasks_by_batch.pop(batch_id, None)

    @classmethod
    def _load_state(cls, batch_id: str) -> MockBatchState | None:
        """Read a batch this process did not submit. None when there is no such batch.

        Not a fallback that invents one: a batch id with no readable record is
        genuinely unknown, and saying so is what lets the caller report it. A
        record missing a field is unreadable in the same sense — it says nothing
        about a batch — rather than an error to raise from a status check.
        """
        try:
            path = cls._state_dir() / f"{batch_id}.json"
            stored = json.loads(path.read_text(encoding="utf-8"))
            state = MockBatchState(
                batch_id=stored["batch_id"],
                status=stored["status"],
                poll_count=stored["poll_count"],
                polls_until_complete=stored["polls_until_complete"],
                created_at=stored["created_at"],
                complete_after_seconds=stored["complete_after_seconds"],
            )
            tasks = stored["tasks"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, PathManagerError):
            logger.debug("No readable batch record for %s", batch_id)
            return None
        cls._batches[batch_id] = state
        cls._tasks_by_batch[batch_id] = tasks
        return state

    @classmethod
    def _state_for(cls, batch_id: str) -> MockBatchState | None:
        """The batch, from this process or from the run that submitted it."""
        cached = cls._batches.get(batch_id)
        return cached if cached is not None else cls._load_state(batch_id)

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from mock state with time-based auto-completion."""
        state = self._state_for(batch_id)
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

        # A poll is state: `polls_until_complete` counts them, and a run that
        # started its count from the submitted value would never reach the
        # threshold — each run polls once and there are two runs by design.
        tasks = self._tasks_by_batch.get(batch_id)
        if tasks is not None:
            self._write_state(state, tasks)
        return state.status

    def _normalize_status(self, raw_status: str) -> str:
        """Status is already normalized."""
        return raw_status

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Generate mock results as JSONL bytes using schema-based fake data."""
        state = self._state_for(batch_id)
        if not state:
            raise ValueError(f"Batch {batch_id} not found")

        tasks = self._tasks_by_batch.get(batch_id, [])
        lines = []

        for task in tasks:
            custom_id = task.get("custom_id", "unknown")

            # Track attempt for this custom_id (for recovery testing)
            attempt = self._get_attempt_for_custom_id(custom_id)

            # Straight off the task this client wrote, which holds both.
            openai_response = FakeDataGenerator.generate_openai_response(
                custom_id, task.get("schema"), task.get("prompt"), attempt
            )

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
        self._write_state(state, tasks)

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
        for stale in cls._state_dir().glob("*.json"):
            stale.unlink(missing_ok=True)
        logger.debug("AgacBatchClient state reset")

    @classmethod
    def get_batch_state(cls, batch_id: str) -> MockBatchState | None:
        """Get internal state of a batch (for testing/debugging)."""
        return cls._state_for(batch_id)
